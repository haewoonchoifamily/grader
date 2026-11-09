"""자동 채점기 — 실행: python app.py   (CLI: python app.py --cli 정답지 학생1 학생2 ... -o 결과.xlsx)"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from export import export_xlsx  # noqa: E402
from grader import DEFAULT_MODEL, run_grading  # noqa: E402
from readers import SUPPORTED_EXTS  # noqa: E402

FILETYPES = [
    ("지원 파일", "*.hwp *.hwpx *.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
    ("한글", "*.hwp *.hwpx"),
    ("PDF", "*.pdf"),
    ("이미지", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
]


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("시험 자동 채점기 (HWP · PDF · 이미지)")
    root.geometry("980x680")

    state = {"key": None, "students": [], "key_q": None, "results": []}
    q: "queue.Queue" = queue.Queue()

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    # --- API 키 / 모델
    top = ttk.LabelFrame(frm, text="1. Claude API 설정", padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="API 키").grid(row=0, column=0, sticky="w")
    api_var = tk.StringVar(value=os.environ.get("ANTHROPIC_API_KEY", ""))
    ttk.Entry(top, textvariable=api_var, show="•", width=52).grid(row=0, column=1, padx=6)
    ttk.Label(top, text="모델").grid(row=0, column=2, padx=(12, 0))
    model_var = tk.StringVar(value=DEFAULT_MODEL)
    ttk.Entry(top, textvariable=model_var, width=22).grid(row=0, column=3, padx=6)
    ttk.Label(top, text="(비워두면 간이 모드: 텍스트 파일의 객관식/단답형만)", foreground="#666").grid(
        row=1, column=1, columnspan=3, sticky="w"
    )

    # --- 파일 선택
    files = ttk.LabelFrame(frm, text="2. 파일 선택", padding=8)
    files.pack(fill="x", pady=8)
    key_var = tk.StringVar(value="(선택 안 됨)")
    stu_var = tk.StringVar(value="(선택 안 됨)")

    def pick_key():
        p = filedialog.askopenfilename(title="정답지 선택", filetypes=FILETYPES)
        if p:
            state["key"] = p
            key_var.set(p)

    def pick_students():
        ps = filedialog.askopenfilenames(title="학생 시험지 선택 (여러 개 가능)", filetypes=FILETYPES)
        if ps:
            state["students"] = list(ps)
            stu_var.set(f"{len(ps)}개 파일")

    def pick_folder():
        d = filedialog.askdirectory(title="학생 시험지 폴더 선택")
        if d:
            ps = sorted(
                str(p) for p in Path(d).iterdir() if p.suffix.lower() in SUPPORTED_EXTS and p.is_file()
            )
            state["students"] = ps
            stu_var.set(f"{len(ps)}개 파일 ({d})")

    ttk.Button(files, text="정답지 선택…", command=pick_key).grid(row=0, column=0, sticky="w")
    ttk.Label(files, textvariable=key_var).grid(row=0, column=1, sticky="w", padx=8)
    ttk.Button(files, text="학생 시험지 선택…", command=pick_students).grid(row=1, column=0, sticky="w", pady=4)
    ttk.Button(files, text="폴더째 선택…", command=pick_folder).grid(row=1, column=2, padx=6)
    ttk.Label(files, textvariable=stu_var).grid(row=1, column=1, sticky="w", padx=8)

    # --- 실행
    runbar = ttk.Frame(frm)
    runbar.pack(fill="x")
    run_btn = ttk.Button(runbar, text="▶ 채점 시작")
    run_btn.pack(side="left")
    save_btn = ttk.Button(runbar, text="엑셀로 저장…", state="disabled")
    save_btn.pack(side="left", padx=8)
    status_var = tk.StringVar(value="대기 중")
    ttk.Label(runbar, textvariable=status_var).pack(side="left", padx=12)
    bar = ttk.Progressbar(runbar, mode="indeterminate", length=160)
    bar.pack(side="right")

    # --- 결과 표
    cols = ("file", "name", "sid", "score", "max", "warn")
    tv = ttk.Treeview(frm, columns=cols, show="headings", height=10)
    for c, t, w in zip(cols, ["파일", "이름", "학번", "점수", "만점", "확인 필요"], [220, 90, 100, 60, 60, 380]):
        tv.heading(c, text=t)
        tv.column(c, width=w, anchor="w" if c in ("file", "warn") else "center")
    tv.pack(fill="both", expand=True, pady=8)

    detail = tk.Text(frm, height=9, wrap="word", state="disabled")
    detail.pack(fill="x")

    def show_detail(_=None):
        sel = tv.selection()
        if not sel:
            return
        r = state["results"][int(sel[0])]
        lines = [f"{r.file}  —  {r.name} {r.student_id}   {r.total:g}/{r.max_total:g}점\n"]
        mark = {"correct": "O", "wrong": "X", "partial": "△", "blank": "-", "review": "?"}
        for x in r.results:
            lines.append(
                f" {mark.get(x.status,'?')} {x.no}번  학생:[{x.student_answer}]  정답:[{x.correct_answer}]  "
                f"{x.earned:g}/{x.points:g}  {x.comment}\n"
            )
        detail.config(state="normal")
        detail.delete("1.0", "end")
        detail.insert("1.0", "".join(lines))
        detail.config(state="disabled")

    tv.bind("<<TreeviewSelect>>", show_detail)

    def worker():
        try:
            key, results = run_grading(
                state["key"],
                state["students"],
                api_key=api_var.get().strip() or None,
                model=model_var.get().strip() or DEFAULT_MODEL,
                progress=lambda s: q.put(("msg", s)),
                on_result=lambda r: q.put(("res", r)),
            )
            q.put(("done", (key, results)))
        except Exception as e:
            q.put(("err", str(e)))

    def start():
        if not state["key"] or not state["students"]:
            messagebox.showwarning("파일 필요", "정답지와 학생 시험지를 먼저 선택하세요.")
            return
        tv.delete(*tv.get_children())
        state["results"] = []
        run_btn.config(state="disabled")
        save_btn.config(state="disabled")
        bar.start(12)
        threading.Thread(target=worker, daemon=True).start()
        root.after(100, poll)

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "msg":
                    status_var.set(val)
                elif kind == "res":
                    state["results"].append(val)
                    tv.insert(
                        "", "end", iid=str(len(state["results"]) - 1),
                        values=(val.file, val.name, val.student_id, f"{val.total:g}", f"{val.max_total:g}",
                                " | ".join(val.warnings)),
                    )
                elif kind == "done":
                    state["key_q"] = val[0]
                    bar.stop()
                    run_btn.config(state="normal")
                    save_btn.config(state="normal")
                    status_var.set(f"완료: {len(val[1])}명 채점")
                    return
                elif kind == "err":
                    bar.stop()
                    run_btn.config(state="normal")
                    status_var.set("오류")
                    messagebox.showerror("채점 실패", val)
                    return
        except queue.Empty:
            pass
        root.after(100, poll)

    def save():
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                         initialfile="채점결과.xlsx")
        if p:
            export_xlsx(state["key_q"], state["results"], p)
            messagebox.showinfo("저장 완료", p)

    run_btn.config(command=start)
    save_btn.config(command=save)
    root.mainloop()


def run_cli(args):
    key, results = run_grading(args.key, args.students, api_key=args.api_key, progress=print)
    for r in results:
        print(f"{r.file}: {r.name} {r.student_id} {r.total:g}/{r.max_total:g}", *r.warnings, sep="  ")
    if args.output:
        export_xlsx(key, results, args.output)
        print("저장:", args.output)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("key", nargs="?")
    ap.add_argument("students", nargs="*")
    ap.add_argument("-o", "--output")
    ap.add_argument("--api-key")
    a = ap.parse_args()
    if a.cli:
        run_cli(a)
    else:
        run_gui()
