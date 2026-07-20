# -*- coding: utf-8 -*-
"""#2430 폰트 ASCII 메트릭 실측 — 한글 COM 통제 문서 → PDF per-char advance.

각 (폰트, ASCII 글자) 케이스 = 같은 글자 N연속 1문단(SIZE_PT, 자간0, 장평100).
PDF rawdict 의 같은 글자 연속 origin 간격 median = 무신축 advance(em).
공백은 'a␣'×N 교대 패턴에서 (a→a 간격) − w(a) 로 도출.

폰트별 개별 PDF·TSV 를 생성한다(--per-face, 기본). 통합 PDF 는 subset 폰트명이
T1/Haansoft 등으로 병합돼 요청 face 식별이 불가하므로, gen_metrics 가 요구하는
`ladder_<face>.tsv`(요청 face 이름 기준) 규약을 per-face 로 만족시킨다.

사용:
  python tools/task2430/hy_ascii_ladder.py \
      --fonts "한양신명조,한양중고딕,한양견명조,한양견고딕,휴먼명조" \
      --out-dir output/poc/task2430
  # → output/poc/task2430/ladder_<face>.tsv (열: face, code, char, adv_em)
  # 이후: python tools/task2430/gen_metrics.py --ladder-dir output/poc/task2430

Windows + 한컴(pyhwpx) 전제. 경로는 리포지토리 루트 기준(절대 경로 하드코딩 없음).
"""
import argparse
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join("output", "poc", "task2430")
CHARS = [chr(c) for c in range(0x21, 0x7F)]  # 0x21..0x7E (94자), 공백은 별도 패턴
SIZE_PT = 14
N = 12


def gen_pdf(font, pdf_path):
    """한 face 에 대해 ASCII+공백 통제 문단을 담은 PDF 를 생성한다."""
    from pyhwpx import Hwp

    hwp = Hwp(visible=False)
    try:
        hwp.hwp.HAction.Run("FileNew")
        for ch in CHARS + [" "]:
            cs = hwp.hwp.HParameterSet.HCharShape
            hwp.hwp.HAction.GetDefault("CharShape", cs.HSet)
            for lang in ("Hangul", "Latin", "Hanja", "Japanese", "Other", "Symbol", "User"):
                setattr(cs, f"FaceName{lang}", font)
                setattr(cs, f"FontType{lang}", 2)
                setattr(cs, f"Ratio{lang}", 100)
                setattr(cs, f"Spacing{lang}", 0)
            cs.Height = hwp.hwp.PointToHwpUnit(SIZE_PT)
            hwp.hwp.HAction.Execute("CharShape", cs.HSet)
            hwp.insert_text(("a " * N + "a") if ch == " " else ch * N)
            hwp.hwp.HAction.Run("BreakPara")
        hwp.save_as(pdf_path, format="PDF")
    finally:
        try:
            hwp.quit()
        except Exception:  # noqa: BLE001
            pass


def measure_pdf(pdf_path):
    """PDF 에서 문자별 무신축 advance(em) 를 측정한다 → {char: adv_em}."""
    import fitz

    d = fitz.open(pdf_path)
    by_char = {}  # char -> [adv_px,...]
    space_pat = []  # a-a dx 목록(공백폭 도출용)
    for pno in range(d.page_count):
        for blk in d[pno].get_text("rawdict")["blocks"]:
            if blk["type"] != 0:
                continue
            for line in blk["lines"]:
                chars = [c for span in line["spans"] for c in span["chars"]]
                text = "".join(c["c"] for c in chars)
                stripped = text.strip()
                if not stripped:
                    continue
                uniq = set(stripped)
                if uniq <= {"a", " "} and " " in text and "a" in uniq:
                    xs = [c["origin"][0] for c in chars if c["c"] == "a"]
                    if len(xs) >= 4:
                        dxs = [xs[i + 1] - xs[i] for i in range(1, len(xs) - 2)]
                        space_pat.append(statistics.median(dxs))
                elif len(uniq) == 1 and len(stripped) >= 6:
                    ch = stripped[0]
                    xs = [c["origin"][0] for c in chars if c["c"] == ch]
                    if len(xs) >= 4:
                        dxs = [xs[i + 1] - xs[i] for i in range(1, len(xs) - 2)]
                        by_char.setdefault(ch, []).append(statistics.median(dxs))
    out = {ch: statistics.median(v) / SIZE_PT for ch, v in by_char.items()}
    if space_pat and "a" in by_char:
        out[" "] = (statistics.median(space_pat) - statistics.median(by_char["a"])) / SIZE_PT
    return out


def write_ladder(face, adv, tsv_path):
    with open(tsv_path, "w", encoding="utf-8") as fh:
        fh.write("face\tcode\tchar\tadv_em\n")
        for ch, em in sorted(adv.items(), key=lambda kv: ord(kv[0])):
            fh.write(f"{face}\t{ord(ch)}\t{ch!r}\t{em:.4f}\n")


def main():
    ap = argparse.ArgumentParser(description="폰트 ASCII advance 실측 → ladder_<face>.tsv")
    ap.add_argument(
        "--fonts",
        default="한양신명조,한양중고딕,한양견명조,한양견고딕,휴먼명조",
        help="쉼표 구분 face 목록(한글 표시명)",
    )
    ap.add_argument("--out-dir", default=DEFAULT_OUT, help="산출 디렉터리(리포 루트 기준 상대 허용)")
    ap.add_argument("--pdf-only", action="store_true", help="기존 PDF 재측정(COM 생성 생략)")
    a = ap.parse_args()

    out_dir = a.out_dir if os.path.isabs(a.out_dir) else os.path.join(REPO_ROOT, a.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    fonts = [f.strip() for f in a.fonts.split(",") if f.strip()]

    for face in fonts:
        safe = face.replace(" ", "_")
        pdf = os.path.join(out_dir, f"ladder_{safe}.pdf")
        tsv = os.path.join(out_dir, f"ladder_{safe}.tsv")
        if not a.pdf_only:
            gen_pdf(face, pdf)
        if not os.path.exists(pdf):
            print(f"  [skip] {face}: PDF 없음 {pdf}")
            continue
        adv = measure_pdf(pdf)
        write_ladder(face, adv, tsv)
        digs = [adv[c] for c in adv if c.isdigit()]
        dstr = f"digit_em={statistics.mean(digs):.3f}" if digs else "digit 미측정"
        print(f"  {face}: {len(adv)}자 {dstr} → {os.path.relpath(tsv, REPO_ROOT)}")


if __name__ == "__main__":
    main()
