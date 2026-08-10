import csv
import datetime as dt
import os
import tkinter as tk
from tkinter import filedialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from .monitor import Monitor

# CSV columns for the exported snapshot log (PRD 2.3 - Log Exporting).
LOG_FIELDS = [
    "timestamp",
    "sample",
    "memory_mb",
    "cpu_percent",
    "risk_score_percent",
    "system_health_percent",
    "threshold_mb",
    "threshold_breached",
    "status",
]

# ---- Design tokens -------------------------------------------------------

BG = "#0b1220"            # window background
PANEL = "#131e31"         # cards / panels
AXES_BG = "#0f1729"       # chart area
BORDER = "#263452"        # hairline borders
TEXT = "#e6edf7"          # primary text
MUTED = "#8ea0bf"         # secondary text

MEMORY_COLOR = "#38bdf8"
CPU_COLOR = "#fb923c"
RISK_COLOR = "#fbbf24"
HEALTH_COLOR = "#34d399"
DANGER_COLOR = "#f87171"

STATUS_COLORS = {
    "stable": HEALTH_COLOR,
    "warning": DANGER_COLOR,
    "stopped": MUTED,
    "notice": RISK_COLOR,
}

FONT_CHOICES = [
    "Segoe UI", "Inter", "Roboto", "Ubuntu", "Noto Sans",
    "DejaVu Sans", "Arial", "Helvetica",
]


def pick_font_family() -> str:
    try:
        from tkinter import font as tkfont

        available = set(tkfont.families())
        for name in FONT_CHOICES:
            if name in available:
                return name
    except Exception:
        pass
    return "TkDefaultFont"


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AI Memory Leak and Resource Anomaly Detection Platform")
        self.root.geometry("1440x900")
        self.root.minsize(1280, 800)
        self.root.configure(bg=BG)

        self.font = pick_font_family()

        self.monitor = Monitor()
        self.after_id = None
        self.threshold = 500.0
        self.history_limit = 70
        self.was_warning = False

        # Sliding window that feeds the live chart.
        self.times = []
        self.memory_values = []
        self.cpu_values = []

        # Persistent history of every flagged warning point: (second, memory_mb).
        self.alert_points = []

        # Timestamped snapshot records collected while monitoring runs.
        self.snapshot_logs = []

        self.memory_text = tk.StringVar(value="0 MB")
        self.cpu_text = tk.StringVar(value="0 %")
        self.risk_text = tk.StringVar(value="0 %")
        self.health_text = tk.StringVar(value="100 %")
        self.status_text = tk.StringVar(value="System Stable")
        self.threshold_text = tk.StringVar(value="500")
        self.samples_text = tk.StringVar(value="Samples recorded: 0")
        self.export_text = tk.StringVar(value="Last export: —")

        self.build_ui()
        self.seed_graph()

    # ------------------------------------------------------------------ UI

    def build_ui(self) -> None:
        self.build_status_bar()

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=24, pady=(18, 14))

        self.build_header(main)

        tk.Frame(main, bg=BORDER, height=1).pack(fill="x", pady=(14, 16))

        self.build_cards(main)
        self.build_controls(main)
        self.build_chart(main)

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_header(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=BG)
        header.pack(fill="x")

        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="AI Memory Leak & Resource Anomaly Detection",
            font=(self.font, 20, "bold"),
            bg=BG,
            fg=TEXT,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            title_box,
            text=f"Real-time telemetry · Isolation Forest scoring · {self.monitor.backend_text}",
            font=(self.font, 10),
            bg=BG,
            fg=MUTED,
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        # Status pill on the right.
        pill = tk.Frame(header, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        pill.pack(side="right", anchor="center", ipadx=14, ipady=6)

        self.status_dot = tk.Label(
            pill, text="●", font=(self.font, 11), bg=PANEL, fg=HEALTH_COLOR
        )
        self.status_dot.pack(side="left", padx=(2, 6))

        self.status_label = tk.Label(
            pill,
            textvariable=self.status_text,
            font=(self.font, 10, "bold"),
            bg=PANEL,
            fg=HEALTH_COLOR,
        )
        self.status_label.pack(side="left")

    def build_cards(self, parent: tk.Frame) -> None:
        cards = tk.Frame(parent, bg=BG)
        cards.pack(fill="x", pady=(0, 16))

        self.create_card(cards, "Memory Usage", self.memory_text, MEMORY_COLOR).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        self.create_card(cards, "CPU Usage", self.cpu_text, CPU_COLOR).pack(
            side="left", fill="x", expand=True, padx=8
        )
        self.create_card(cards, "Leak Risk", self.risk_text, RISK_COLOR).pack(
            side="left", fill="x", expand=True, padx=8
        )
        self.create_card(cards, "System Health", self.health_text, HEALTH_COLOR).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )

    def create_card(self, parent: tk.Frame, title: str, value_var: tk.StringVar, color: str) -> tk.Frame:
        card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, height=112)
        card.pack_propagate(False)

        tk.Frame(card, bg=color, height=3).pack(fill="x")

        inner = tk.Frame(card, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=18, pady=12)

        tk.Label(
            inner,
            text=title.upper(),
            font=(self.font, 9, "bold"),
            bg=PANEL,
            fg=MUTED,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            textvariable=value_var,
            font=(self.font, 26, "bold"),
            bg=PANEL,
            fg=color,
            anchor="w",
        ).pack(fill="x", pady=(4, 0))
        return card

    def build_controls(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill="x", pady=(0, 16), ipady=10)

        inner = tk.Frame(bar, bg=PANEL)
        inner.pack(padx=16)

        tk.Label(
            inner,
            text="MEMORY THRESHOLD (MB)",
            font=(self.font, 9, "bold"),
            bg=PANEL,
            fg=MUTED,
        ).pack(side="left", padx=(0, 10))

        tk.Entry(
            inner,
            textvariable=self.threshold_text,
            width=7,
            justify="center",
            font=(self.font, 11),
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=MEMORY_COLOR,
        ).pack(side="left", padx=(0, 10), ipady=4)

        self.create_button(inner, "Set", self.set_threshold, "#33455f", "#41597a").pack(side="left", padx=(0, 22))
        self.create_button(inner, "Start", self.start, "#15803d", "#16a34a").pack(side="left", padx=(0, 8))
        self.create_button(inner, "Stop", self.stop, "#b91c1c", "#dc2626").pack(side="left", padx=(0, 22))
        self.create_button(inner, "Export Logs", self.export_logs, "#1d4ed8", "#2563eb").pack(side="left")

    def create_button(self, parent: tk.Frame, text: str, command, bg: str, hover: str) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=(self.font, 10, "bold"),
            bg=bg,
            fg="#ffffff",
            activebackground=hover,
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=20,
            pady=7,
            cursor="hand2",
        )
        button.bind("<Enter>", lambda _event: button.config(bg=hover))
        button.bind("<Leave>", lambda _event: button.config(bg=bg))
        return button

    def build_chart(self, parent: tk.Frame) -> None:
        panel = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        panel.pack(fill="both", expand=True)

        head = tk.Frame(panel, bg=PANEL)
        head.pack(fill="x", padx=18, pady=(12, 0))

        tk.Label(
            head,
            text="Resource Usage Over Time",
            font=(self.font, 13, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(side="left")
        tk.Label(
            head,
            text="Live · 1 s refresh",
            font=(self.font, 9),
            bg=PANEL,
            fg=MUTED,
        ).pack(side="right")

        self.figure = Figure(figsize=(11.5, 5.0), dpi=100)
        self.figure.patch.set_facecolor(PANEL)

        # Dual-axis chart: Memory (MB) on the left axis, CPU (%) on the right.
        self.memory_axis = self.figure.add_subplot(111)
        self.cpu_axis = self.memory_axis.twinx()

        self.memory_axis.set_facecolor(AXES_BG)
        self.memory_axis.grid(True, linestyle="-", linewidth=0.6, alpha=0.55, color="#2c3e5f")
        self.memory_axis.set_xlabel("Time (s)", color=MUTED, fontsize=11)
        self.memory_axis.set_ylabel("Memory (MB)", color=MEMORY_COLOR, fontsize=11)
        self.cpu_axis.set_ylabel("CPU (%)", color=CPU_COLOR, fontsize=11)
        self.cpu_axis.set_ylim(0, 100)
        self.memory_axis.xaxis.set_major_locator(MaxNLocator(10, integer=True))

        self.memory_axis.tick_params(axis="x", colors=MUTED, labelsize=9)
        self.memory_axis.tick_params(axis="y", colors=MUTED, labelsize=9)
        self.cpu_axis.tick_params(axis="y", colors=MUTED, labelsize=9)

        for spine in self.memory_axis.spines.values():
            spine.set_color(BORDER)
        for spine in self.cpu_axis.spines.values():
            spine.set_color(BORDER)

        self.memory_line, = self.memory_axis.plot([], [], color=MEMORY_COLOR, linewidth=2.2)
        self.cpu_line, = self.cpu_axis.plot([], [], color=CPU_COLOR, linewidth=2.2)
        self.threshold_line, = self.memory_axis.plot(
            [], [], color=RISK_COLOR, linestyle="--", linewidth=1.6, alpha=0.95
        )
        self.alert_scatter = self.memory_axis.scatter(
            [], [], color=DANGER_COLOR, s=64, marker="x", linewidths=2.0, zorder=5
        )

        self.memory_axis.legend(
            [self.memory_line, self.cpu_line, self.threshold_line, self.alert_scatter],
            ["Memory (MB)", "CPU (%)", "Memory Threshold", "Warning Points"],
            loc="upper left",
            fontsize=9,
            facecolor=PANEL,
            edgecolor=BORDER,
            labelcolor=TEXT,
            framealpha=0.95,
        )

        self.figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.figure, master=panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=14, pady=(6, 12))

    def build_status_bar(self) -> None:
        bar = tk.Frame(self.root, bg="#080d17", highlightbackground=BORDER, highlightthickness=1)
        bar.pack(side="bottom", fill="x")

        tk.Label(
            bar,
            text=self.monitor.backend_text,
            font=(self.font, 9),
            bg="#080d17",
            fg=MUTED,
        ).pack(side="left", padx=14, pady=4)

        right = tk.Frame(bar, bg="#080d17")
        right.pack(side="right", padx=14)

        tk.Label(
            right,
            textvariable=self.samples_text,
            font=(self.font, 9),
            bg="#080d17",
            fg=MUTED,
        ).pack(side="left", padx=(0, 16))
        tk.Label(
            right,
            textvariable=self.export_text,
            font=(self.font, 9),
            bg="#080d17",
            fg=MUTED,
        ).pack(side="left")

    # -------------------------------------------------------------- status

    def set_status(self, text: str, kind: str = "stable") -> None:
        color = STATUS_COLORS.get(kind, HEALTH_COLOR)
        self.status_text.set(text)
        self.status_label.config(fg=color)
        self.status_dot.config(fg=color)

    # -------------------------------------------------------------- logic

    def seed_graph(self) -> None:
        # Fill the graph once so the dashboard does not look empty at the start.
        data = None
        for _ in range(18):
            data = self.monitor.next_data(self.threshold)
            self.add_history(data)
        if data is not None:
            self.update_cards(data)
        self.redraw_graph()

    def read_threshold(self) -> float:
        try:
            value = float(self.threshold_text.get())
            if value > 0:
                return value
        except (ValueError, tk.TclError):
            pass
        self.threshold_text.set(str(int(self.threshold)))
        return self.threshold

    def set_threshold(self) -> None:
        self.threshold = self.read_threshold()
        self.set_status(f"Threshold Set: {self.threshold:.0f} MB", "notice")
        self.redraw_graph()

    def start(self) -> None:
        self.stop()
        self.threshold = self.read_threshold()
        self.set_status("System Stable", "stable")
        self.update_loop()

    def stop(self) -> None:
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.set_status("System Stopped", "stopped")

    def update_loop(self) -> None:
        data = self.monitor.next_data(self.threshold)
        self.add_history(data)
        self.update_cards(data)
        self.record_snapshot(data)

        warning_now = data.leak
        if warning_now:
            # Flag every warning sample so the scatter shows all flagged points.
            self.alert_points.append((data.second, data.memory_mb))
            self.set_status("System Warning", "warning")
        else:
            self.set_status("System Stable", "stable")

        self.was_warning = warning_now
        self.redraw_graph()
        self.after_id = self.root.after(1000, self.update_loop)

    def update_cards(self, data) -> None:
        health = max(0, 100 - data.score)
        self.memory_text.set(f"{data.memory_mb:.0f} MB")
        self.cpu_text.set(f"{data.cpu_percent:.0f} %")
        self.risk_text.set(f"{data.score} %")
        self.health_text.set(f"{health} %")

    def record_snapshot(self, data) -> None:
        # One timestamped snapshot record per sample for CSV export (PRD 2.3).
        health = max(0, 100 - data.score)
        breached = data.memory_mb > self.threshold
        self.snapshot_logs.append(
            {
                "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sample": data.second,
                "memory_mb": f"{data.memory_mb:.2f}",
                "cpu_percent": f"{data.cpu_percent:.2f}",
                "risk_score_percent": data.score,
                "system_health_percent": health,
                "threshold_mb": f"{self.threshold:.0f}",
                "threshold_breached": "YES" if breached else "NO",
                "status": "WARNING" if data.leak else "STABLE",
            }
        )
        self.samples_text.set(f"Samples recorded: {len(self.snapshot_logs)}")

    def add_history(self, data) -> None:
        self.times.append(data.second)
        self.memory_values.append(data.memory_mb)
        self.cpu_values.append(data.cpu_percent)

        if len(self.times) > self.history_limit:
            self.times.pop(0)
            self.memory_values.pop(0)
            self.cpu_values.pop(0)

    def redraw_graph(self) -> None:
        if not self.times:
            return

        # Update both graph lines using the latest history lists.
        self.memory_line.set_data(self.times, self.memory_values)
        self.cpu_line.set_data(self.times, self.cpu_values)

        window_start = self.times[0]
        window_end = max(self.times[-1], window_start + 1)

        # Draw every flagged warning point that falls inside the visible window.
        visible_alerts = [
            (second, memory_mb)
            for second, memory_mb in self.alert_points
            if second >= window_start
        ]
        if visible_alerts:
            self.alert_scatter.set_offsets(visible_alerts)
            self.alert_scatter.set_visible(True)
        else:
            self.alert_scatter.set_offsets([[0.0, 0.0]])
            self.alert_scatter.set_visible(False)

        # Threshold reference line across the whole visible window.
        self.threshold_line.set_data([window_start, window_end], [self.threshold, self.threshold])

        self.memory_axis.set_xlim(window_start, window_end)

        # Keep the threshold line inside the visible y-range so breaches are clear.
        minimum = min(min(self.memory_values), self.threshold)
        maximum = max(max(self.memory_values), self.threshold)
        padding = max(10.0, (maximum - minimum) * 0.25)
        self.memory_axis.set_ylim(minimum - padding, maximum + padding)

        self.canvas.draw_idle()

    def export_logs(self) -> None:
        if not self.snapshot_logs:
            self.set_status("No Logs To Export", "notice")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save logs",
            defaultextension=".csv",
            initialfile=f"monitoring_logs_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not file_path:
            return

        with open(file_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=LOG_FIELDS)
            writer.writeheader()
            writer.writerows(self.snapshot_logs)

        self.export_text.set(f"Last export: {os.path.basename(file_path)}")
        self.set_status(f"Logs Exported ({len(self.snapshot_logs)} records)", "stopped")

    def close(self) -> None:
        self.stop()
        self.monitor.close()
        self.root.destroy()


def run_app() -> None:
    App().root.mainloop()
