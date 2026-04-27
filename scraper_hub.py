#!/usr/bin/env python3
"""Desktop launcher that brings every scraper/downloader into one app."""

from __future__ import annotations

import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk


ROOT_DIR = Path(__file__).resolve().parent


class ScraperHub(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Web Scrapper Hub")
        self.geometry("1120x760")
        self.minsize(980, 680)

        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.current_command: list[str] = []
        self.current_cwd: Path = ROOT_DIR

        self._configure_theme()
        self._build_layout()
        self.after(100, self._drain_output_queue)

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(10, 6))
        style.configure("Primary.TButton", padding=(12, 7))
        style.configure("TLabel", padding=(0, 2))
        style.configure("TNotebook.Tab", padding=(14, 8))
        style.configure("Section.TLabelframe", padding=10)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Web Scrapper Hub", font=("Segoe UI", 18, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(header, textvariable=self.status_var).pack(side="right")

        body = ttk.PanedWindow(outer, orient="vertical")
        body.pack(fill="both", expand=True)

        top = ttk.Frame(body)
        bottom = ttk.Frame(body)
        body.add(top, weight=3)
        body.add(bottom, weight=2)

        self.tabs = ttk.Notebook(top)
        self.tabs.pack(fill="both", expand=True)

        self._build_products_tab()
        self._build_influencer_tab()
        self._build_truecaller_tab()
        self._build_stocks_tab()
        self._build_video_tab()

        controls = ttk.Frame(bottom)
        controls.pack(fill="x", pady=(10, 6))
        ttk.Button(controls, text="Run", style="Primary.TButton", command=self.run_current_tab).pack(side="left")
        ttk.Button(controls, text="Stop", command=self.stop_process).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Clear Log", command=self.clear_log).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Open Output Folder", command=self.open_current_output_folder).pack(
            side="right"
        )

        command_frame = ttk.LabelFrame(bottom, text="Command", padding=8)
        command_frame.pack(fill="x", pady=(0, 8))
        self.command_var = tk.StringVar(value="")
        ttk.Entry(command_frame, textvariable=self.command_var, state="readonly").pack(fill="x")

        log_frame = ttk.LabelFrame(bottom, text="Live Log", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log = scrolledtext.ScrolledText(log_frame, wrap="word", height=12, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)

    def _build_products_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Products")

        self.product_engine = tk.StringVar(value="playwright")
        self.product_site = tk.StringVar(value="all")
        self.product_output = tk.StringVar(
            value=str(ROOT_DIR / "Alibaba_Indiamart_scrapper" / "products_output.csv")
        )
        self.product_headful = tk.BooleanVar(value=False)

        row = ttk.Frame(tab)
        row.pack(fill="x")
        self._radio_group(row, "Engine", self.product_engine, [("Playwright", "playwright"), ("Requests", "requests")])
        self._radio_group(row, "Site", self.product_site, [("Both", "all"), ("IndiaMart", "indiamart"), ("Alibaba", "alibaba")])
        ttk.Checkbutton(row, text="Show browser", variable=self.product_headful).pack(side="left", padx=20)

        ttk.Label(tab, text="Search queries, one per line").pack(anchor="w", pady=(16, 4))
        self.product_queries = tk.Text(tab, height=8, wrap="word")
        self.product_queries.insert("1.0", "steel pipes\ncopper wire")
        self.product_queries.pack(fill="x")

        self._path_row(tab, "Output CSV", self.product_output, save=True)

    def _build_influencer_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Influencers")

        base = ROOT_DIR / "Influencer_Marketing_Scrapper"
        self.influencer_config = tk.StringVar(value=str(base / "markets.sample.json"))
        self.influencer_output = tk.StringVar(value=str(base / "output"))
        self.influencer_history = tk.StringVar(value=str(base / "output" / "seen_profiles.csv"))
        self.influencer_seed = tk.StringVar(value="")
        self.influencer_market = tk.StringVar(value="india")
        self.influencer_all_markets = tk.BooleanVar(value=False)
        self.influencer_platforms = tk.StringVar(value="")
        self.influencer_limit = tk.IntVar(value=10)
        self.influencer_allow_weak = tk.BooleanVar(value=False)

        self._path_row(tab, "Market config", self.influencer_config)
        self._path_row(tab, "Output folder", self.influencer_output, directory=True)
        self._path_row(tab, "History CSV", self.influencer_history, save=True)
        self._path_row(tab, "Seed file", self.influencer_seed)
        self._entry_row(tab, "Market", self.influencer_market)
        ttk.Checkbutton(tab, text="Run all markets", variable=self.influencer_all_markets).pack(anchor="w", pady=4)
        self._entry_row(tab, "Platforms", self.influencer_platforms, hint="Optional: instagram facebook youtube")
        self._entry_row(tab, "Limit per query", self.influencer_limit)
        ttk.Checkbutton(tab, text="Allow weak discovery", variable=self.influencer_allow_weak).pack(anchor="w", pady=4)

    def _build_truecaller_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Truecaller")

        base = ROOT_DIR / "truecaller_scraper"
        self.truecaller_csv = tk.StringVar(value="")
        self.truecaller_column = tk.StringVar(value="")
        self.truecaller_output = tk.StringVar(value=str(base / "results"))
        self.truecaller_speed = tk.StringVar(value="balanced")
        self.truecaller_local_only = tk.BooleanVar(value=False)

        self._path_row(tab, "Input CSV", self.truecaller_csv)
        self._entry_row(tab, "Phone column", self.truecaller_column, hint="Leave blank to auto-detect")
        self._path_row(tab, "Output folder", self.truecaller_output, directory=True)
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Speed", width=16).pack(side="left")
        ttk.Combobox(row, textvariable=self.truecaller_speed, values=["safe", "balanced", "fast"], state="readonly", width=18).pack(side="left")
        ttk.Checkbutton(tab, text="Local validation only", variable=self.truecaller_local_only).pack(anchor="w", pady=4)

    def _build_stocks_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Stocks")

        self.stock_india = tk.BooleanVar(value=True)
        self.stock_us = tk.BooleanVar(value=True)
        self.stock_output = tk.StringVar(value=str(ROOT_DIR / "Stock_Market_Scraper" / "output"))
        self.stock_batch_size = tk.StringVar(value="80")
        self.stock_delay = tk.StringVar(value="0.4")
        self.stock_limit = tk.StringVar(value="")
        self.stock_json = tk.BooleanVar(value=False)
        self.stock_zip = tk.BooleanVar(value=False)
        self.stock_use_env_proxies = tk.BooleanVar(value=False)

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(row, text="India NSE", variable=self.stock_india).pack(side="left")
        ttk.Checkbutton(row, text="US Nasdaq/NYSE/AMEX", variable=self.stock_us).pack(side="left", padx=(16, 0))

        ttk.Label(tab, text="Extra Yahoo symbols, one per line").pack(anchor="w", pady=(8, 4))
        self.stock_symbols = tk.Text(tab, height=6, wrap="word")
        self.stock_symbols.insert("1.0", "TCS.NS\nAAPL")
        self.stock_symbols.pack(fill="x")

        self._path_row(tab, "Output folder", self.stock_output, directory=True)
        self._entry_row(tab, "Batch size", self.stock_batch_size)
        self._entry_row(tab, "Delay seconds", self.stock_delay)
        self._entry_row(tab, "Limit", self.stock_limit, hint="Optional, useful for testing")
        ttk.Checkbutton(tab, text="Also write JSON", variable=self.stock_json).pack(anchor="w", pady=4)
        ttk.Checkbutton(tab, text="Create ZIP archive", variable=self.stock_zip).pack(anchor="w", pady=4)
        ttk.Checkbutton(tab, text="Use environment proxies", variable=self.stock_use_env_proxies).pack(anchor="w", pady=4)

    def _build_video_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(tab, text="Videos")

        self.video_mode = tk.StringVar(value="universal")
        self.video_output = tk.StringVar(value=str(ROOT_DIR / "downloads"))
        self.video_quality = tk.StringVar(value="best")
        self.video_audio = tk.BooleanVar(value=False)
        self.video_subtitles = tk.BooleanVar(value=False)
        self.video_info = tk.BooleanVar(value=False)
        self.video_limit = tk.StringVar(value="")
        self.video_cookies = tk.StringVar(value="")

        row = ttk.Frame(tab)
        row.pack(fill="x")
        self._radio_group(row, "Downloader", self.video_mode, [("Universal", "universal"), ("YouTube", "youtube")])
        ttk.Label(row, text="Quality").pack(side="left", padx=(22, 6))
        ttk.Combobox(
            row,
            textvariable=self.video_quality,
            values=["best", "1080p", "720p", "480p", "360p", "audio"],
            state="readonly",
            width=12,
        ).pack(side="left")

        ttk.Label(tab, text="Video URLs, one per line").pack(anchor="w", pady=(16, 4))
        self.video_urls = tk.Text(tab, height=8, wrap="word")
        self.video_urls.pack(fill="x")

        self._path_row(tab, "Output folder", self.video_output, directory=True)
        self._entry_row(tab, "Max playlist items", self.video_limit)
        self._path_row(tab, "Cookies file", self.video_cookies)
        ttk.Checkbutton(tab, text="Audio only (universal downloader)", variable=self.video_audio).pack(anchor="w", pady=4)
        ttk.Checkbutton(tab, text="Download English subtitles", variable=self.video_subtitles).pack(anchor="w", pady=4)
        ttk.Checkbutton(tab, text="Show info only", variable=self.video_info).pack(anchor="w", pady=4)

    def _radio_group(self, parent: ttk.Frame, label: str, variable: tk.StringVar, options: list[tuple[str, str]]) -> None:
        frame = ttk.LabelFrame(parent, text=label, padding=8)
        frame.pack(side="left", padx=(0, 10))
        for text, value in options:
            ttk.Radiobutton(frame, text=text, value=value, variable=variable).pack(side="left", padx=4)

    def _entry_row(self, parent: ttk.Frame, label: str, variable: tk.Variable, hint: str = "") -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text=label, width=16).pack(side="left")
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True)
        if hint:
            ttk.Label(row, text=hint).pack(side="left", padx=(8, 0))

    def _path_row(self, parent: ttk.Frame, label: str, variable: tk.StringVar, directory: bool = False, save: bool = False) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text=label, width=16).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=lambda: self._browse_path(variable, directory, save)).pack(side="left", padx=(8, 0))

    def _browse_path(self, variable: tk.StringVar, directory: bool, save: bool) -> None:
        if directory:
            value = filedialog.askdirectory(initialdir=str(ROOT_DIR))
        elif save:
            value = filedialog.asksaveasfilename(initialdir=str(ROOT_DIR))
        else:
            value = filedialog.askopenfilename(initialdir=str(ROOT_DIR))
        if value:
            variable.set(value)

    def run_current_tab(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showinfo("Already running", "A task is already running. Stop it before starting another.")
            return

        try:
            command, cwd = self._command_for_selected_tab()
        except ValueError as exc:
            messagebox.showerror("Missing input", str(exc))
            return

        self.current_command = command
        self.current_cwd = cwd
        self.command_var.set(self._format_command(command, cwd))
        self._append_log(f"\n$ {self.command_var.get()}\n")
        self.status_var.set("Running")

        thread = threading.Thread(target=self._run_process, args=(command, cwd), daemon=True)
        thread.start()

    def _command_for_selected_tab(self) -> tuple[list[str], Path]:
        selected = self.tabs.tab(self.tabs.select(), "text")
        if selected == "Products":
            return self._product_command()
        if selected == "Influencers":
            return self._influencer_command()
        if selected == "Truecaller":
            return self._truecaller_command()
        if selected == "Stocks":
            return self._stocks_command()
        if selected == "Videos":
            return self._video_command()
        raise ValueError("Unknown tab selected.")

    def _product_command(self) -> tuple[list[str], Path]:
        cwd = ROOT_DIR / "Alibaba_Indiamart_scrapper"
        script = "scraper_playwright.py" if self.product_engine.get() == "playwright" else "scraper_requests.py"
        queries = self._lines(self.product_queries)
        if not queries:
            raise ValueError("Enter at least one product query.")
        output = self.product_output.get().strip()
        if not output:
            raise ValueError("Choose an output CSV for product results.")

        cmd = [sys.executable, script, "--site", self.product_site.get(), "--output", output]
        for query in queries:
            cmd.extend(["--query", query])
        if script == "scraper_playwright.py" and self.product_headful.get():
            cmd.append("--headful")
        return cmd, cwd

    def _influencer_command(self) -> tuple[list[str], Path]:
        cwd = ROOT_DIR / "Influencer_Marketing_Scrapper"
        config = self.influencer_config.get().strip()
        output = self.influencer_output.get().strip()
        if not config:
            raise ValueError("Choose a market config JSON.")
        if not output:
            raise ValueError("Choose an influencer output folder.")

        cmd = [sys.executable, "run_scraper.py", "--config", config, "--output-dir", output]
        if self.influencer_all_markets.get():
            cmd.append("--all-markets")
        else:
            market = self.influencer_market.get().strip()
            if not market:
                raise ValueError("Enter a market or enable all markets.")
            cmd.extend(["--market", market])
        platforms = self.influencer_platforms.get().split()
        if platforms:
            cmd.append("--platform")
            cmd.extend(platforms)
        if self.influencer_seed.get().strip():
            cmd.extend(["--seed-file", self.influencer_seed.get().strip()])
        if self.influencer_history.get().strip():
            cmd.extend(["--history-file", self.influencer_history.get().strip()])
        cmd.extend(["--limit-per-query", str(self.influencer_limit.get())])
        if self.influencer_allow_weak.get():
            cmd.append("--allow-weak-discovery")
        return cmd, cwd

    def _truecaller_command(self) -> tuple[list[str], Path]:
        cwd = ROOT_DIR / "truecaller_scraper"
        csv_file = self.truecaller_csv.get().strip()
        if not csv_file:
            raise ValueError("Choose a Truecaller input CSV.")
        cmd = [
            sys.executable,
            "run_scraper.py",
            csv_file,
            "--output-dir",
            self.truecaller_output.get().strip() or str(cwd / "results"),
            "--speed",
            self.truecaller_speed.get(),
        ]
        if self.truecaller_column.get().strip():
            cmd.extend(["--column", self.truecaller_column.get().strip()])
        if self.truecaller_local_only.get():
            cmd.append("--local-only")
        return cmd, cwd

    def _stocks_command(self) -> tuple[list[str], Path]:
        cwd = ROOT_DIR / "Stock_Market_Scraper"
        markets = []
        if self.stock_india.get():
            markets.append("india")
        if self.stock_us.get():
            markets.append("us")
        if not markets:
            raise ValueError("Choose at least one stock market: India or US.")

        cmd = [
            sys.executable,
            "stock_price_scraper.py",
            "--output-dir",
            self.stock_output.get().strip() or str(cwd / "output"),
            "--batch-size",
            self.stock_batch_size.get().strip() or "80",
            "--delay",
            self.stock_delay.get().strip() or "0.4",
        ]
        for market in markets:
            cmd.extend(["--market", market])
        for symbol in self._lines(self.stock_symbols):
            cmd.extend(["--symbol", symbol])
        if self.stock_limit.get().strip():
            cmd.extend(["--limit", self.stock_limit.get().strip()])
        if self.stock_json.get():
            cmd.append("--json")
        if self.stock_zip.get():
            cmd.append("--zip")
        if self.stock_use_env_proxies.get():
            cmd.append("--use-env-proxies")
        return cmd, cwd

    def _video_command(self) -> tuple[list[str], Path]:
        cwd = ROOT_DIR / "Video_Downloader"
        urls = self._lines(self.video_urls)
        if not urls:
            raise ValueError("Enter at least one video URL.")
        output = self.video_output.get().strip() or str(ROOT_DIR / "downloads")
        limit = self.video_limit.get().strip()
        cookies = self.video_cookies.get().strip()

        if self.video_mode.get() == "youtube":
            cmd = [sys.executable, "youtube_downloader.py", urls[0], "--quality", self.video_quality.get(), "--output", output]
            if limit:
                cmd.extend(["--max", limit])
            return cmd, cwd

        cmd = [sys.executable, "video_downloader.py", *urls, "--quality", self.video_quality.get(), "--output", output]
        if self.video_audio.get():
            cmd.append("--audio")
        if self.video_subtitles.get():
            cmd.append("--subtitles")
        if self.video_info.get():
            cmd.append("--info")
        if limit:
            cmd.extend(["--max", limit])
        if cookies:
            cmd.extend(["--cookies", cookies])
        return cmd, cwd

    def _run_process(self, command: list[str], cwd: Path) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=flags,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.output_queue.put(line)
            return_code = self.process.wait()
            self.output_queue.put(f"\nProcess finished with exit code {return_code}.\n")
        except Exception as exc:
            self.output_queue.put(f"\nFailed to run command: {exc}\n")
        finally:
            self.output_queue.put("__STATUS_READY__")

    def stop_process(self) -> None:
        if not self.process or self.process.poll() is not None:
            self.status_var.set("Ready")
            return
        self._append_log("\nStopping process...\n")
        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()
        except Exception:
            self.process.terminate()

    def clear_log(self) -> None:
        self.log.delete("1.0", "end")

    def open_current_output_folder(self) -> None:
        selected = self.tabs.tab(self.tabs.select(), "text")
        if selected == "Products":
            path = Path(self.product_output.get()).expanduser().resolve().parent
        elif selected == "Influencers":
            path = Path(self.influencer_output.get()).expanduser().resolve()
        elif selected == "Truecaller":
            path = Path(self.truecaller_output.get()).expanduser().resolve()
        elif selected == "Stocks":
            path = Path(self.stock_output.get()).expanduser().resolve()
        else:
            path = Path(self.video_output.get()).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path) if os.name == "nt" else subprocess.Popen(["xdg-open", str(path)])

    def _drain_output_queue(self) -> None:
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if item == "__STATUS_READY__":
                self.status_var.set("Ready")
                self.process = None
            else:
                self._append_log(item)
        self.after(100, self._drain_output_queue)

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text)
        self.log.see("end")

    def _lines(self, widget: tk.Text) -> list[str]:
        return [line.strip() for line in widget.get("1.0", "end").splitlines() if line.strip()]

    def _format_command(self, command: list[str], cwd: Path) -> str:
        return f"cd {shlex.quote(str(cwd))} ; " + " ".join(shlex.quote(part) for part in command)


def main() -> int:
    app = ScraperHub()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
