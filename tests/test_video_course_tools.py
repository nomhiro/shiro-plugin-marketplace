"""udemy-video-course のスクリプトのうち、外部依存なしで確かめられる判定を単体で検証する。

ffmpeg・TTS・STT・OCR を呼ぶ部分は CI で回せないので、判定を純粋な関数に切り出し、そこだけを見る。
"""
import pytest


# ---------------------------------------------------------------- verify_tts
def test_lecture_speech_names_follow_transcript_order_not_slide_number():
    """本文の無いスライドが途中にあると、speech_NN はスライド番号とずれる。"""
    from verify_tts import lecture_speech_names
    secs = {"slide_01": "表紙", "slide_02": "", "slide_03": "本文", "slide_10": "まとめ"}
    assert lecture_speech_names(secs) == {
        "slide_01": "speech_01.wav", "slide_03": "speech_02.wav", "slide_10": "speech_03.wav"}


def test_all_empty_means_the_endpoint_is_broken():
    from verify_tts import all_empty
    assert all_empty([{"recognized": ""}, {"recognized": " "}])
    assert not all_empty([{"recognized": ""}, {"recognized": "読めた"}])
    assert not all_empty([{"recognized": ""}])          # 1区間だけでは判断しない
