# -*- coding: utf-8 -*-
"""#2430 HY 계열 ASCII 메트릭 실측 — 한글 COM 통제 문서 → PDF per-char advance.

각 (폰트, ASCII 글자) 케이스 = 같은 글자 12연속 1문단 (14pt, 자간0, 장평100).
PDF rawdict 의 같은 글자 연속 origin 간격 median = 무신축 advance.
공백은 'a␣'×12 교대 패턴에서 (a→a 간격) − w(a) 로 도출.

산출: hy_ascii_measured.tsv (font, char_code, adv_em)
사용: python tools/task2430/hy_ascii_ladder.py [--pdf-only]
"""
import os
import statistics
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = r"C:\Users\planet\rhwp\output\poc\task2430"
PDF = os.path.join(OUT_DIR, "hy_ascii_ladder.pdf")
TSV = os.path.join(OUT_DIR, "hy_ascii_measured.tsv")

FONTS = ["HY신명조", "HY중고딕", "HY견고딕", "HY견명조", "HY헤드라인M", "HY그래픽", "HY궁서"]
CHARS = [chr(c) for c in range(0x21, 0x7F)]  # 94자; 공백은 별도 패턴
SIZE_PT = 14
N = 12


def generate():
    from pyhwpx import Hwp

    os.makedirs(OUT_DIR, exist_ok=True)
    hwp = Hwp(visible=False)
    try:
        hwp.hwp.HAction.Run("FileNew")
        cases = []
        for font in FONTS:
            for ch in CHARS + [" "]:
                cases.append((font, ch))
        for font, ch in cases:
            cs = hwp.hwp.HParameterSet.HCharShape
            hwp.hwp.HAction.GetDefault("CharShape", cs.HSet)
            for lang in ("Hangul", "Latin", "Hanja", "Japanese", "Other", "Symbol", "User"):
                setattr(cs, f"FaceName{lang}", font)
                setattr(cs, f"FontType{lang}", 2)
                setattr(cs, f"Ratio{lang}", 100)
                setattr(cs, f"Spacing{lang}", 0)
            cs.Height = hwp.hwp.PointToHwpUnit(SIZE_PT)
            hwp.hwp.HAction.Execute("CharShape", cs.HSet)
            if ch == " ":
                hwp.insert_text("a " * N + "a")
            else:
                hwp.insert_text(ch * N)
            hwp.hwp.HAction.Run("BreakPara")
        hwp.save_as(PDF, format="PDF")
        print(f"generated cases={len(cases)} → {PDF}")
        return cases
    finally:
        try:
            hwp.quit()
        except Exception:
            pass


def cases_list():
    return [(font, ch) for font in FONTS for ch in CHARS + [" "]]


def measure(cases):
    import fitz

    d = fitz.open(PDF)
    # span_font+char 로 자체 식별 (문서/PDF 순서 비의존)
    by_key = {}  # (span_font, char) -> [adv_px,...]
    space_pat = {}  # span_font -> [a-a dx,...]
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
                span_font = line["spans"][0].get("font", "?")
                uniq = set(stripped)
                if uniq <= {"a", " "} and " " in text and "a" in uniq:
                    xs = [c["origin"][0] for c in chars if c["c"] == "a"]
                    if len(xs) >= 4:
                        dxs = [xs[i + 1] - xs[i] for i in range(1, len(xs) - 2)]
                        space_pat.setdefault(span_font, []).append(statistics.median(dxs))
                elif len(uniq) == 1 and len(stripped) >= 6:
                    ch = stripped[0]
                    xs = [c["origin"][0] for c in chars if c["c"] == ch]
                    if len(xs) >= 4:
                        dxs = [xs[i + 1] - xs[i] for i in range(1, len(xs) - 2)]
                        by_key.setdefault((span_font, ch), []).append(statistics.median(dxs))
    span_fonts = sorted({sf for sf, _ in by_key})
    print(f"pdf span fonts={span_fonts}")
    rows = []
    for (sf, ch), dxs in sorted(by_key.items()):
        rows.append((sf, ch, statistics.median(dxs) / SIZE_PT, sf))
    for sf, dxs in space_pat.items():
        wa = by_key.get((sf, "a"))
        if wa:
            adv = statistics.median(dxs) - statistics.median(wa)
            rows.append((sf, " ", adv / SIZE_PT, sf))
    dup = sum(1 for v in by_key.values() if len(v) > 1)
    print(f"keys={len(by_key)} dup_key={dup} (동일 폰트가 여러 표시명에 매핑되면 병합됨)")
    with open(TSV, "w", encoding="utf-8") as fh:
        fh.write("font\tcode\tchar\tadv_em\tspan_font\n")
        for font, ch, em, sf in rows:
            fh.write(f"{font}\t{ord(ch)}\t{ch!r}\t{em:.4f}\t{sf}\n")
    print(f"→ {TSV} ({len(rows)} rows)")
    # 요약: span 폰트별 숫자·마침표
    for sf in sorted({f for f, _, _, _ in rows}):
        digs = [em for f, ch, em, _ in rows if f == sf and ch.isdigit()]
        dots = [em for f, ch, em, _ in rows if f == sf and ch == "."]
        if digs:
            print(f"  {sf}: digit_em avg={statistics.mean(digs):.3f} '.'={dots[0]:.3f}" if dots else f"  {sf}: digit avg={statistics.mean(digs):.3f}")


def main():
    if "--pdf-only" in sys.argv:
        cases = cases_list()
    else:
        cases = generate()
        time.sleep(1)
    measure(cases)


if __name__ == "__main__":
    main()
