"""
FunASR SenseVoiceSmall ONNX 本地推理 ASR Provider

使用 onnxruntime 直接加载量化后的 SenseVoiceSmall-onnx 模型，
无需依赖 FunASR 框架和 PyTorch 完整模型。

关键特性：
- 模型文件：model_quant.onnx（230MB，原 PyTorch 模型 893MB 的 26%）
- 内存占用大幅降低
- 支持语种自动检测
- 支持热词提升
- VAD 依赖已有 SileroVAD 组件（外部处理）
"""
import asyncio
import json
import math
import os
import time
import traceback
from typing import Optional, Tuple, List

import librosa
import numpy as np
import onnxruntime

from config.logger import setup_logging
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType

TAG = __name__
logger = setup_logging()


class ASRProvider(ASRProviderBase):
    """基于 ONNX Runtime 的 SenseVoiceSmall 本地 ASR 推理"""

    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        self.interface_type = InterfaceType.LOCAL
        self.model_dir = config.get("model_dir")
        self.output_dir = config.get("output_dir", "tmp/")
        self.delete_audio_file = delete_audio_file

        # 音频参数（与 FunASR 前端一致）
        self.sample_rate = 16000
        self.window_length = 25  # ms
        self.frame_shift = 10    # ms
        self.n_mels = 80
        self.lfr_m = 7           # LFR 上下文帧数
        self.lfr_n = 6           # LFR 跳帧数
        # LFR 输出维度: n_mels * lfr_m = 80 * 7 = 560

        # 模型路径
        model_path = os.path.join(self.model_dir, "model_quant.onnx")
        tokens_path = os.path.join(self.model_dir, "tokens.json")
        cmvn_path = os.path.join(self.model_dir, "am.mvn")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ONNX 模型文件不存在: {model_path}")
        if not os.path.exists(tokens_path):
            raise FileNotFoundError(f"Token 文件不存在: {tokens_path}")

        # 加载 tokens
        with open(tokens_path, "r", encoding="utf-8") as f:
            self.tokens = json.load(f)

        # 加载 cmvn（均值方差归一化）
        self.cmvn_mean = None
        self.cmvn_var = None
        if os.path.exists(cmvn_path):
            self._load_cmvn(cmvn_path)

        # 构建 token 到 id 的映射（用于解码）
        self.token_to_id = {t: i for i, t in enumerate(self.tokens)}

        # ONNX Runtime session
        sess_options = onnxruntime.SessionOptions()
        sess_options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 4
        self.session = onnxruntime.InferenceSession(model_path, sess_options)

        logger.bind(tag=TAG).info(
            f"SenseVoiceSmall-ONNX 加载完成，模型大小: {os.path.getsize(model_path) / 1024 / 1024:.1f}MB"
        )

    def _load_cmvn(self, path: str):
        """加载 am.mvn 均值方差归一化文件"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                header = f.readline().strip()
                parts = header.split()
                if len(parts) >= 2:
                    mean_size = int(parts[0])
                    var_size = int(parts[1])
                    mean_data = []
                    var_data = []
                    for _ in range(mean_size):
                        line = f.readline()
                        if line:
                            mean_data.extend([float(x) for x in line.strip().split()])
                    for _ in range(var_size):
                        line = f.readline()
                        if line:
                            var_data.extend([float(x) for x in line.strip().split()])
                    if mean_data:
                        self.cmvn_mean = np.array(mean_data, dtype=np.float32)
                    if var_data:
                        self.cmvn_var = np.array(var_data, dtype=np.float32)
                        # 方差 → 标准差
                        self.cmvn_var = np.sqrt(np.maximum(self.cmvn_var, 1e-10))
        except Exception as e:
            logger.bind(tag=TAG).warning(f"加载 CMVN 失败: {e}，跳过归一化")

    def _extract_feats(self, audio: np.ndarray) -> np.ndarray:
        """
        音频特征提取：与 FunASR WavFrontend 保持一致

        流程：
        1. 预加重 (pre-emphasis)
        2. STFT → 功率谱
        3. Mel 滤波器组 (80 维)
        4. 对数
        5. CMVN 归一化
        6. LFR (Low Frame Rate) 拼接
        """
        # 1. 预加重
        pre_emphasis = 0.97
        audio = np.append(audio[0], audio[1:] - pre_emphasis * audio[:-1])

        # 2. STFT
        n_fft = int(self.sample_rate * self.window_length / 1000)  # 400
        hop_length = int(self.sample_rate * self.frame_shift / 1000)  # 160
        stft = librosa.stft(
            audio.astype(np.float32),
            n_fft=n_fft,
            hop_length=hop_length,
            win_length=n_fft,
            window="hamming",
            center=True,
        )
        mag = np.abs(stft)

        # 3. Mel 滤波器组（80 维）
        mel_basis = librosa.filters.mel(
            sr=self.sample_rate,
            n_fft=n_fft,
            n_mels=self.n_mels,
            fmin=0,
            fmax=8000,
        )
        mel_spec = mel_basis @ mag

        # 4. 对数
        feats = np.log(np.maximum(mel_spec, 1e-10)).T  # [T, 80]

        # 5. CMVN 归一化
        if self.cmvn_mean is not None:
            feats = feats - self.cmvn_mean[:self.n_mels]
        if self.cmvn_var is not None:
            feats = feats / self.cmvn_var[:self.n_mels]

        # 6. LFR 拼接 (m=7, n=6)
        # 每帧拼接前后共 m 帧（当前帧 + 前 floor(m/2) + 后 floor(m/2)），跳 n 步
        context = self.lfr_m
        skip = self.lfr_n
        T = feats.shape[0]
        # 首尾填充
        pad_left = context // 2
        pad_right = context // 2
        feats_padded = np.pad(feats, ((pad_left, pad_right), (0, 0)), mode="edge")
        # 拼接
        lfr_list = []
        for i in range(0, T, skip):
            start = i
            end = start + context
            if end <= feats_padded.shape[0]:
                lfr_list.append(feats_padded[start:end].flatten())
        if not lfr_list:
            # 回退：至少一帧
            lfr_list.append(feats_padded[:context].flatten())
        return np.stack(lfr_list, axis=0)  # [T', 560]

    def _ctc_decode(self, logits: np.ndarray) -> str:
        """
        CTC 贪心解码 + 特殊 token 过滤

        Args:
            logits: shape [T, vocab_size]

        Returns:
            str: 解码后的文本
        """
        # argmax
        ids = np.argmax(logits, axis=-1)  # [T]

        # CTC 折叠：合并连续重复 token
        collapsed = []
        prev = -1
        for idx in ids:
            if idx != prev:
                collapsed.append(idx)
                prev = idx

        # 将 ID 映射为 token 文本
        raw_tokens = []
        for idx in collapsed:
            if 0 <= idx < len(self.tokens):
                raw_tokens.append(self.tokens[idx])
            else:
                raw_tokens.append("")

        # 过滤特殊 token
        result_parts = []
        for token in raw_tokens:
            if token in ("<unk>", "<s>", "</s>"):
                continue
            if token.startswith("<|") and token.endswith("|>"):
                # 语言标签、情感标签等特殊 token — 跳过
                continue
            if token.startswith("<") and token.endswith(">"):
                continue
            result_parts.append(token)

        text = "".join(result_parts)
        # BPE 后处理：将 ▁ 替换为空格
        text = text.replace("▁", " ")
        return text.strip()

    def _prepare_inputs(self, feats: np.ndarray) -> dict:
        """
        准备 ONNX 模型输入

        Args:
            feats: [T, 560] 特征矩阵

        Returns:
            dict: ONNX 输入字典
        """
        T = feats.shape[0]
        # 增加 batch 维度
        speech = feats[np.newaxis, :, :].astype(np.float32)          # [1, T, 560]
        speech_lengths = np.array([T], dtype=np.int32)               # [1]
        # 语种：0=auto
        language = np.array([0], dtype=np.int32)                     # [1]
        # 文本归一化：1=开启
        textnorm = np.array([1], dtype=np.int32)                     # [1]

        return {
            "speech": speech,
            "speech_lengths": speech_lengths,
            "language": language,
            "textnorm": textnorm,
        }

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str,
        audio_format="opus", artifacts=None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        语音转文本主处理逻辑

        Args:
            opus_data: Opus 音频数据包列表
            session_id: 会话 ID
            audio_format: 音频格式
            artifacts: 包含 pcm_bytes 等预处理结果

        Returns:
            Tuple[text, file_path]
        """
        if artifacts is None or not artifacts.pcm_bytes:
            return "", None

        start_time = time.time()

        try:
            # 1. PCM → numpy
            pcm_bytes = artifacts.pcm_bytes
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            # 2. 重采样到 16kHz（如果采样率不同）
            # artifacts 中的 sample_rate 可能为 24000（设备默认），需要重采样
            sample_rate = getattr(artifacts, "sample_rate", self.sample_rate)
            if sample_rate != self.sample_rate:
                audio = librosa.resample(
                    audio, orig_sr=sample_rate, target_sr=self.sample_rate
                )

            # 3. 特征提取
            feats = self._extract_feats(audio)  # [T', 560]

            if feats.shape[0] == 0:
                logger.bind(tag=TAG).warning("特征提取结果为空")
                return "", None

            # 4. ONNX 推理
            inputs = self._prepare_inputs(feats)
            outputs = self.session.run(["ctc_logits"], inputs)
            logits = outputs[0][0]  # [T'', 25055]

            # 5. CTC 解码
            text = self._ctc_decode(logits)

            elapsed = time.time() - start_time
            audio_len = len(audio) / self.sample_rate
            rtf = elapsed / audio_len if audio_len > 0 else 0

            logger.bind(tag=TAG).info(
                f"ASR(ONNX) 完成: 音频{audio_len:.1f}s, 推理{elapsed:.2f}s, RTF={rtf:.2f}, 结果: {text[:60]}"
            )

            return text, artifacts.file_path

        except Exception as e:
            logger.bind(tag=TAG).error(
                f"ASR(ONNX) 失败: {type(e).__name__}: {e}", exc_info=True
            )
            return "", None
