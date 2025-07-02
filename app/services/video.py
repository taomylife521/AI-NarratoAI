import traceback

# import pysrt
from typing import Optional
from typing import List
from loguru import logger
from moviepy import *
from PIL import ImageFont
from contextlib import contextmanager
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
    CompositeAudioClip
)


from app.models.schema import VideoAspect, SubtitlePosition


def wrap_text(text, max_width, font, fontsize=60):
    """
    文本自动换行处理
    Args:
        text: 待处理的文本
        max_width: 最大宽度
        font: 字体文件路径
        fontsize: 字体大小

    Returns:
        tuple: (换行后的文本, 文本高度)
    """
    # 创建字体对象
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    logger.debug(f"换行文本, 最大宽度: {max_width}, 文本宽度: {width}, 文本: {text}")

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        # logger.warning(f"wrapped text: {result}")
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    logger.debug(f"换行文本: {result}")
    return result, height


@contextmanager
def manage_clip(clip):
    """
    视频片段资源管理器
    Args:
        clip: 视频片段对象

    Yields:
        VideoFileClip: 视频片段对象
    """
    try:
        yield clip
    finally:
        clip.close()
        del clip


def resize_video_with_padding(clip, target_width: int, target_height: int):
    """
    调整视频尺寸并添加黑边
    Args:
        clip: 视频片段
        target_width: 目标宽度
        target_height: 目标高度

    Returns:
        CompositeVideoClip: 调整尺寸后的视频
    """
    clip_ratio = clip.w / clip.h
    target_ratio = target_width / target_height

    if clip_ratio == target_ratio:
        return clip.resize((target_width, target_height))

    if clip_ratio > target_ratio:
        scale_factor = target_width / clip.w
    else:
        scale_factor = target_height / clip.h

    new_width = int(clip.w * scale_factor)
    new_height = int(clip.h * scale_factor)
    clip_resized = clip.resize(newsize=(new_width, new_height))

    background = ColorClip(
        size=(target_width, target_height),
        color=(0, 0, 0)
    ).set_duration(clip.duration)

    return CompositeVideoClip([
        background,
        clip_resized.set_position("center")
    ])


def loop_audio_clip(audio_clip: AudioFileClip, target_duration: float) -> AudioFileClip:
    """
    循环音频片段直到达到目标时长

    参数:
        audio_clip: 原始音频片段
        target_duration: 目标时长（秒）
    返回:
        循环后的音频片段
    """
    # 计算需要循环的次数
    loops_needed = int(target_duration / audio_clip.duration) + 1

    # 创建足够长的音频
    extended_audio = audio_clip
    for _ in range(loops_needed - 1):
        extended_audio = CompositeAudioClip([
            extended_audio,
            audio_clip.set_start(extended_audio.duration)
        ])

    # 裁剪到目标时长
    return extended_audio.subclip(0, target_duration)


def calculate_subtitle_position(position, video_height: int, text_height: int = 0) -> tuple:
    """
    计算字幕在视频中的具体位置
    
    Args:
        position: 位置配置，可以是 SubtitlePosition 枚举值或表示距顶部百分比的浮点数
        video_height: 视频高度
        text_height: 字幕文本高度
    
    Returns:
        tuple: (x, y) 坐标
    """
    margin = 50  # 字幕距离边缘的边距
    
    if isinstance(position, (int, float)):
        # 百分比位置
        return ('center', int(video_height * position))
    
    # 预设位置
    if position == SubtitlePosition.TOP:
        return ('center', margin)
    elif position == SubtitlePosition.CENTER:
        return ('center', video_height // 2)
    elif position == SubtitlePosition.BOTTOM:
        return ('center', video_height - margin - text_height)
    
    # 默认底部
    return ('center', video_height - margin - text_height)


def generate_video_v3(
        video_path: str,
        subtitle_style: dict,
        volume_config: dict,
        subtitle_path: Optional[str] = None,
        bgm_path: Optional[str] = None,
        narration_path: Optional[str] = None,
        output_path: str = "output.mp4",
        font_path: Optional[str] = None,
        subtitle_enabled: bool = True
) -> None:
    """
    合并视频素材，包括视频、字幕、BGM和解说音频

    参数:
        video_path: 原视频文件路径
        subtitle_path: SRT字幕文件路径（可选）
        bgm_path: 背景音乐文件路径（可选）
        narration_path: 解说音频文件路径（可选）
        output_path: 输出文件路径
        volume_config: 音量配置字典，可包含以下键：
            - original: 原声音量（0-1），默认1.0
            - bgm: BGM音量（0-1），默认0.3
            - narration: 解说音量（0-1），默认1.0
        subtitle_enabled: 是否启用字幕，默认True
        subtitle_style: 字幕样式配置字典，可包含以下键：
            - font: 字体名称
            - fontsize: 字体大小
            - color: 字体颜色
            - stroke_color: 描边颜色
            - stroke_width: 描边宽度
            - bg_color: 背景色
            - position: 位置支持 SubtitlePosition 枚举值或 0-1 之间的浮点数（表示距顶部的百分比）
            - method: 文字渲染方法
        font_path: 字体文件路径（.ttf/.otf 等格式）
    """
    # 检查视频文件是否存在
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    # 加载视频
    video = VideoFileClip(video_path)
    subtitle_clips = []

    # 处理字幕（如果启用且提供）- 修复字幕开关bug
    if subtitle_enabled and subtitle_path:
        if os.path.exists(subtitle_path):
            # 检查字体文件
            if font_path and not os.path.exists(font_path):
                logger.warning(f"警告：字体文件不存在: {font_path}")

            try:
                subs = pysrt.open(subtitle_path)
                logger.info(f"读取到 {len(subs)} 条字幕")

                for index, sub in enumerate(subs):
                    start_time = sub.start.ordinal / 1000
                    end_time = sub.end.ordinal / 1000

                    try:
                        # 检查字幕文本是否为空
                        if not sub.text or sub.text.strip() == '':
                            logger.info(f"警告：第 {index + 1} 条字幕内容为空，已跳过")
                            continue

                        # 处理字幕文本：确保是字符串，并处理可能的列表情况
                        if isinstance(sub.text, (list, tuple)):
                            subtitle_text = ' '.join(str(item) for item in sub.text if item is not None)
                        else:
                            subtitle_text = str(sub.text)

                        subtitle_text = subtitle_text.strip()

                        if not subtitle_text:
                            logger.info(f"警告：第 {index + 1} 条字幕处理后为空，已跳过")
                            continue

                        # 创建临时 TextClip 来获取文本高度
                        temp_clip = TextClip(
                            subtitle_text,
                            font=font_path,
                            fontsize=subtitle_style['fontsize'],
                            color=subtitle_style['color']
                        )
                        text_height = temp_clip.h
                        temp_clip.close()

                        # 计算字幕位置
                        position = calculate_subtitle_position(
                            subtitle_style['position'],
                            video.h,
                            text_height
                        )

                        # 创建最终的 TextClip
                        text_clip = (TextClip(
                            subtitle_text,
                            font=font_path,
                            fontsize=subtitle_style['fontsize'],
                            color=subtitle_style['color']
                        )
                            .set_position(position)
                            .set_duration(end_time - start_time)
                            .set_start(start_time))
                        subtitle_clips.append(text_clip)

                    except Exception as e:
                        logger.error(f"警告：创建第 {index + 1} 条字幕时出错: {traceback.format_exc()}")

                logger.info(f"成功创建 {len(subtitle_clips)} 条字幕剪辑")
            except Exception as e:
                logger.info(f"警告：处理字幕文件时出错: {str(e)}")
        else:
            logger.warning(f"字幕文件不存在: {subtitle_path}")
    elif not subtitle_enabled:
        logger.info("字幕已禁用，跳过字幕处理")
    elif not subtitle_path:
        logger.info("未提供字幕文件路径，跳过字幕处理")

    # 合并音频
    audio_clips = []

    # 添加原声（设置音量）
    logger.info(f"音量配置详情: {volume_config}")
    if video.audio is not None:
        original_volume = volume_config['original']
        logger.info(f"应用原声音量: {original_volume}")
        original_audio = video.audio.volumex(original_volume)
        audio_clips.append(original_audio)
        logger.info("原声音频已添加到合成列表")
    else:
        logger.warning("视频没有音轨，无法添加原声")

    # 添加BGM（如果提供）
    if bgm_path:
        logger.info(f"添加背景音乐: {bgm_path}")
        bgm = AudioFileClip(bgm_path)
        if bgm.duration < video.duration:
            bgm = loop_audio_clip(bgm, video.duration)
        else:
            bgm = bgm.subclip(0, video.duration)
        bgm_volume = volume_config['bgm']
        logger.info(f"应用BGM音量: {bgm_volume}")
        bgm = bgm.volumex(bgm_volume)
        audio_clips.append(bgm)

    # 添加解说音频（如果提供）
    if narration_path:
        logger.info(f"添加解说音频: {narration_path}")
        narration_volume = volume_config['narration']
        logger.info(f"应用解说音量: {narration_volume}")
        narration = AudioFileClip(narration_path).volumex(narration_volume)
        audio_clips.append(narration)

    # 合成最终视频（包含字幕）
    if subtitle_clips:
        final_video = CompositeVideoClip([video] + subtitle_clips, size=video.size)
    else:
        logger.info("警告：没有字幕被添加到视频中")
        final_video = video

    if audio_clips:
        logger.info(f"合成音频轨道，共 {len(audio_clips)} 个音频片段")
        final_audio = CompositeAudioClip(audio_clips)
        final_video = final_video.set_audio(final_audio)
        logger.info("音频合成完成")
    else:
        logger.warning("没有音频轨道需要合成")

    # 导出视频 - 使用优化的编码器
    logger.info("开始导出视频...")

    # 获取最优编码器
    from app.utils import ffmpeg_utils
    optimal_encoder = ffmpeg_utils.get_optimal_ffmpeg_encoder()

    # 根据编码器类型设置参数
    ffmpeg_params = []
    if "nvenc" in optimal_encoder:
        ffmpeg_params = ['-preset', 'medium', '-profile:v', 'high']
    elif "videotoolbox" in optimal_encoder:
        ffmpeg_params = ['-profile:v', 'high']
    elif "qsv" in optimal_encoder:
        ffmpeg_params = ['-preset', 'medium']
    elif "vaapi" in optimal_encoder:
        ffmpeg_params = ['-profile', '100']
    elif optimal_encoder == "libx264":
        ffmpeg_params = ['-preset', 'medium', '-crf', '23']

    try:
        final_video.write_videofile(
            output_path,
            codec=optimal_encoder,
            audio_codec='aac',
            fps=video.fps,
            ffmpeg_params=ffmpeg_params
        )
        logger.info(f"视频已导出到: {output_path} (使用编码器: {optimal_encoder})")
    except Exception as e:
        logger.warning(f"使用 {optimal_encoder} 编码器失败: {str(e)}, 尝试软件编码")
        # 降级到软件编码
        final_video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            fps=video.fps,
            ffmpeg_params=['-preset', 'medium', '-crf', '23']
        )
        logger.info(f"视频已导出到: {output_path} (使用软件编码)")

    # 清理资源
    video.close()
    for clip in subtitle_clips:
        clip.close()
    if bgm_path:
        bgm.close()
    if narration_path:
        narration.close()
