"""채점 결과 -> 엑셀(.xlsx)"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

STATUS_KO = {"correct": "정답", "wrong": "오답", "partial": "부분점수", "blank": "무응답", "review": "확인필요"}
FILL = {
    "correct": PatternFill("solid", fgColor="E2F0D9"),
    "wrong": PatternFill("solid", fgColor="F8D7DA"),
    "partial": PatternFill("solid", fgColor="FFF2CC"),
    "blank": PatternFill("solid", fgColor="EDEDED"),
    "review": PatternFill("solid", fgColor="FCE4D6"),
}
HEAD = PatternFill("solid", fgColor="1F3864")


def _head(ws, row, values):
    for c, v in enumerate(values, 1):
        cell = ws.cell(row=row, column=c, value=v)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center")


def export_xlsx(key, results, path: str):
    wb = Workbook()

    # 1) 요약
    ws = wb.active
    ws.title = "요약"
    _head(ws, 1, ["파일", "이름", "학번", "점수", "만점", "정답률(%)", "확인 필요 사항"])
    for i, r in enumerate(results, 2):
        ws.append(
            [
                r.file,
                r.name,
                r.student_id,
                r.total,
                r.max_total,
                None,
                " | ".join(r.warnings),
            ]
        )
        ws.cell(row=i, column=6, value=f"=IF(E{i}=0,0,ROUND(D{i}/E{i}*100,1))")
        if r.warnings:
            ws.cell(row=i, column=7).fill = FILL["review"]
    n = len(results)
    if n:
        ws.cell(row=n + 3, column=3, value="평균").font = Font(bold=True)
        ws.cell(row=n + 3, column=4, value=f"=ROUND(AVERAGE(D2:D{n+1}),2)")
        ws.cell(row=n + 4, column=3, value="최고").font = Font(bold=True)
        ws.cell(row=n + 4, column=4, value=f"=MAX(D2:D{n+1})")
        ws.cell(row=n + 5, column=3, value="최저").font = Font(bold=True)
        ws.cell(row=n + 5, column=4, value=f"=MIN(D2:D{n+1})")
    for col, w in zip("ABCDEFG", [28, 12, 14, 8, 8, 12, 60]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    # 2) 문항별 상세
    wd = wb.create_sheet("문항별 상세")
    _head(wd, 1, ["파일", "이름", "문항", "학생 답", "정답", "득점", "배점", "결과", "코멘트"])
    row = 2
    for r in results:
        for q in r.results:
            wd.append(
                [r.file, r.name, q.no, q.student_answer, q.correct_answer, q.earned, q.points,
                 STATUS_KO.get(q.status, q.status), q.comment]
            )
            wd.cell(row=row, column=8).fill = FILL.get(q.status, FILL["blank"])
            wd.cell(row=row, column=4).alignment = Alignment(wrap_text=True, vertical="top")
            wd.cell(row=row, column=9).alignment = Alignment(wrap_text=True, vertical="top")
            row += 1
    for col, w in zip("ABCDEFGHI", [28, 12, 7, 40, 30, 8, 8, 10, 45]):
        wd.column_dimensions[col].width = w
    wd.freeze_panes = "A2"
    wd.auto_filter.ref = f"A1:I{max(row-1,1)}"

    # 3) 문항별 정답률 (출제 분석)
    wa = wb.create_sheet("문항 분석")
    _head(wa, 1, ["문항", "유형", "정답", "배점", "평균 득점률(%)", "응시"])
    for q in key:
        got = [x for r in results for x in r.results if x.no == q.no]
        rate = round(sum(x.earned for x in got) / (len(got) * q.points) * 100, 1) if got else 0
        wa.append([q.no, q.type, q.answer, q.points, rate, len(got)])
    for col, w in zip("ABCDEF", [8, 10, 40, 8, 16, 8]):
        wa.column_dimensions[get_column_letter(ord(col) - 64)].width = w

    wb.save(path)
