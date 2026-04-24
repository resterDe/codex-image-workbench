#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageTk  # type: ignore
except ImportError:  # pragma: no cover
    Image = None
    ImageTk = None


SKILL_NAME = "Codex Image Workbench"
HOST = "127.0.0.1"
PORT = 48551
MAX_HISTORY = 48

WINDOW_BG = "#0d1117"
PANEL_BG = "#121821"
SURFACE_BG = "#161f2b"
MUTED_BG = "#0f1620"
TEXT_PRIMARY = "#f5f7fb"
TEXT_SECONDARY = "#94a3b8"
ACCENT = "#f59e0b"
ACCENT_SOFT = "#2a1d08"
BORDER = "#243041"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open or update the singleton preview window for Codex Image Workbench."
    )
    parser.add_argument("images", nargs="+", help="Absolute or relative image paths.")
    parser.add_argument(
        "--title",
        default=SKILL_NAME,
        help="Window title. Defaults to the skill name.",
    )
    return parser.parse_args()


def normalize_payload(images: list[str], title: str) -> dict[str, object]:
    return {
        "title": title or SKILL_NAME,
        "images": [str(Path(item).expanduser().resolve()) for item in images],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def try_send_update(payload: dict[str, object], timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as client:
            client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return True
    except OSError:
        return False


class SingletonServer(threading.Thread):
    def __init__(self, updates: "queue.Queue[dict[str, object]]") -> None:
        super().__init__(daemon=True)
        self.updates = updates
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, PORT))
        self.sock.listen(5)

    def run(self) -> None:
        while True:
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            with conn:
                data = bytearray()
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data.extend(chunk)
            if not data:
                continue
            try:
                payload = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self.updates.put(payload)


class ModernButton(tk.Label):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: callable,
        *,
        primary: bool = False,
        width: int = 12,
    ) -> None:
        bg = ACCENT if primary else MUTED_BG
        fg = "#111827" if primary else TEXT_PRIMARY
        super().__init__(
            master,
            text=text,
            bg=bg,
            fg=fg,
            padx=16,
            pady=10,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            width=width,
            relief="flat",
            bd=0,
        )
        self.default_bg = bg
        self.default_fg = fg
        self.hover_bg = "#fbbf24" if primary else "#1c2633"
        self.command = command
        self.bind("<Button-1>", lambda _event: self.command())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event: tk.Event[tk.Misc]) -> None:
        self.configure(bg=self.hover_bg)

    def _on_leave(self, _event: tk.Event[tk.Misc]) -> None:
        self.configure(bg=self.default_bg)

    def set_disabled(self, disabled: bool) -> None:
        if disabled:
            self.configure(bg="#111827", fg="#5b6470", cursor="arrow")
            self.unbind("<Button-1>")
            return
        self.configure(bg=self.default_bg, fg=self.default_fg, cursor="hand2")
        self.bind("<Button-1>", lambda _event: self.command())


class PreviewApp:
    def __init__(
        self,
        root: tk.Tk,
        initial_payload: dict[str, object],
        updates: "queue.Queue[dict[str, object]]",
    ) -> None:
        self.root = root
        self.updates = updates
        self.images: list[Path] = []
        self.index = 0
        self.photo: object | None = None
        self.current_pil_image: Image.Image | None = None
        self.current_zoom = 1.0
        self.fit_zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.is_fullscreen = False
        self.thumbnail_photo_refs: list[object] = []
        self._drag_origin: tuple[int, int] | None = None
        self._pan_origin: tuple[float, float] | None = None
        self._refresh_job: str | None = None

        self.root.title(SKILL_NAME)
        self.root.configure(bg=WINDOW_BG)
        self.root.geometry("1240x920")
        self.root.minsize(920, 680)

        outer = tk.Frame(root, bg=WINDOW_BG)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        header = tk.Frame(outer, bg=WINDOW_BG)
        header.pack(fill="x", pady=(0, 14))

        brand_row = tk.Frame(header, bg=WINDOW_BG)
        brand_row.pack(fill="x")

        chip = tk.Label(
            brand_row,
            text="SKILL",
            bg=ACCENT_SOFT,
            fg=ACCENT,
            padx=10,
            pady=5,
            font=("Segoe UI", 9, "bold"),
        )
        chip.pack(side="left")

        self.window_title = tk.Label(
            brand_row,
            text=SKILL_NAME,
            bg=WINDOW_BG,
            fg=TEXT_PRIMARY,
            font=("Segoe UI Semibold", 22),
        )
        self.window_title.pack(side="left", padx=(14, 0))

        self.counter_label = tk.Label(
            brand_row,
            text="",
            bg=WINDOW_BG,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 10),
        )
        self.counter_label.pack(side="right")

        self.sub_label = tk.Label(
            header,
            text="Preview and save the latest generated image",
            bg=WINDOW_BG,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 10),
        )
        self.sub_label.pack(anchor="w", pady=(8, 0))

        card = tk.Frame(
            outer,
            bg=PANEL_BG,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        card.pack(fill="both", expand=True)

        toolbar = tk.Frame(card, bg=PANEL_BG)
        toolbar.pack(fill="x", padx=18, pady=(18, 12))

        left_tools = tk.Frame(toolbar, bg=PANEL_BG)
        left_tools.pack(side="left")
        self.prev_button = ModernButton(left_tools, "Previous", self.show_previous, width=10)
        self.prev_button.pack(side="left")
        self.next_button = ModernButton(left_tools, "Next", self.show_next, width=10)
        self.next_button.pack(side="left", padx=(10, 0))
        self.fit_button = ModernButton(left_tools, "Fit", self.reset_view, width=8)
        self.fit_button.pack(side="left", padx=(10, 0))

        right_tools = tk.Frame(toolbar, bg=PANEL_BG)
        right_tools.pack(side="right")
        self.zoom_label = tk.Label(
            right_tools,
            text="100%",
            bg=PANEL_BG,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 10, "bold"),
            padx=12,
        )
        self.zoom_label.pack(side="left")
        self.copy_button = ModernButton(right_tools, "Copy Path", self.copy_path, width=10)
        self.copy_button.pack(side="left", padx=(8, 0))
        self.folder_button = ModernButton(right_tools, "Open Folder", self.open_folder, width=11)
        self.folder_button.pack(side="left", padx=(10, 0))
        self.save_button = ModernButton(right_tools, "Download", self.save_as, primary=True, width=10)
        self.save_button.pack(side="left", padx=(10, 0))

        viewer_shell = tk.Frame(card, bg=PANEL_BG)
        viewer_shell.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        self.viewer = tk.Canvas(
            viewer_shell,
            bg=SURFACE_BG,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.viewer.pack(fill="both", expand=True)
        self.viewer.bind("<MouseWheel>", self._on_mousewheel)
        self.viewer.bind("<Button-4>", lambda event: self._on_mousewheel_linux(event, 1))
        self.viewer.bind("<Button-5>", lambda event: self._on_mousewheel_linux(event, -1))
        self.viewer.bind("<Double-Button-1>", self._toggle_fit_actual)
        self.viewer.bind("<ButtonPress-1>", self._start_pan)
        self.viewer.bind("<B1-Motion>", self._move_pan)
        self.viewer.bind("<ButtonRelease-1>", self._end_pan)

        thumbnail_card = tk.Frame(card, bg=PANEL_BG)
        thumbnail_card.pack(fill="x", padx=18, pady=(0, 14))

        self.thumbnail_canvas = tk.Canvas(
            thumbnail_card,
            bg=MUTED_BG,
            height=104,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.thumbnail_canvas.pack(side="left", fill="x", expand=True)

        self.thumbnail_scroll = tk.Scrollbar(
            thumbnail_card,
            orient="horizontal",
            command=self.thumbnail_canvas.xview,
        )
        self.thumbnail_scroll.pack(side="bottom", fill="x")
        self.thumbnail_canvas.configure(xscrollcommand=self.thumbnail_scroll.set)

        self.thumbnail_strip = tk.Frame(self.thumbnail_canvas, bg=MUTED_BG)
        self.thumbnail_canvas_window = self.thumbnail_canvas.create_window(
            (0, 0), window=self.thumbnail_strip, anchor="nw"
        )
        self.thumbnail_strip.bind("<Configure>", self._on_thumbnail_configure)
        self.thumbnail_canvas.bind("<Configure>", self._on_thumbnail_canvas_resize)

        footer = tk.Frame(card, bg=PANEL_BG)
        footer.pack(fill="x", padx=18, pady=(0, 18))

        footer_top = tk.Frame(footer, bg=PANEL_BG)
        footer_top.pack(fill="x")

        self.path_label = tk.Label(
            footer_top,
            text="",
            bg=PANEL_BG,
            fg=TEXT_SECONDARY,
            anchor="w",
            justify="left",
            font=("Consolas", 10),
        )
        self.path_label.pack(side="left", fill="x", expand=True)

        self.detail_label = tk.Label(
            footer_top,
            text="",
            bg=PANEL_BG,
            fg=TEXT_SECONDARY,
            anchor="e",
            justify="right",
            font=("Segoe UI", 10),
        )
        self.detail_label.pack(side="right")

        self.status_label = tk.Label(
            footer,
            text="",
            bg=PANEL_BG,
            fg=TEXT_SECONDARY,
            anchor="w",
            justify="left",
            font=("Segoe UI", 10),
        )
        self.status_label.pack(fill="x", pady=(8, 0))

        root.bind("<Left>", lambda _event: self.show_previous())
        root.bind("<Right>", lambda _event: self.show_next())
        root.bind("<space>", self._on_space_next)
        root.bind("<Shift-space>", self._on_space_previous)
        root.bind("f", self._toggle_fullscreen)
        root.bind("F", self._toggle_fullscreen)
        root.bind("<F11>", self._toggle_fullscreen)
        root.bind("<Escape>", lambda _event: self.root.destroy())
        root.bind("0", lambda _event: self.reset_view())
        root.bind("<Control-0>", lambda _event: self.reset_view())
        root.bind("<Configure>", self._schedule_refresh)

        self.apply_payload(initial_payload)
        self._poll_updates()

    def _poll_updates(self) -> None:
        try:
            while True:
                payload = self.updates.get_nowait()
                self.apply_payload(payload)
        except queue.Empty:
            pass
        self.root.after(160, self._poll_updates)

    def _on_space_next(self, _event: tk.Event[tk.Misc]) -> str:
        self.show_next()
        return "break"

    def _on_space_previous(self, _event: tk.Event[tk.Misc]) -> str:
        self.show_previous()
        return "break"

    def _toggle_fullscreen(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)
        return "break"

    def _schedule_refresh(self, _event: tk.Event[tk.Misc]) -> None:
        if self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(120, self._refresh_after_resize)

    def _refresh_after_resize(self) -> None:
        if self.current_pil_image is not None:
            previous_fit = self.fit_zoom
            new_fit = self._fit_zoom_for_image(*self.current_pil_image.size)
            if abs(self.current_zoom - previous_fit) < 0.02:
                self.fit_zoom = new_fit
                self.current_zoom = new_fit
                self.pan_x = 0.0
                self.pan_y = 0.0
            else:
                self.fit_zoom = new_fit
            self._update_zoom_label()
            self._update_detail_label()
        self._render_current_image()

    def _viewer_bounds(self) -> tuple[int, int]:
        return max(self.viewer.winfo_width(), 1), max(self.viewer.winfo_height(), 1)

    def _on_thumbnail_configure(self, _event: tk.Event[tk.Misc]) -> None:
        self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox("all"))

    def _on_thumbnail_canvas_resize(self, event: tk.Event[tk.Misc]) -> None:
        self.thumbnail_canvas.itemconfigure(self.thumbnail_canvas_window, height=event.height)

    def _update_zoom_label(self) -> None:
        self.zoom_label.configure(text=f"{round(self.current_zoom * 100)}%")

    def _update_detail_label(self) -> None:
        total = len(self.images)
        current = self.index + 1 if total else 0
        if self.current_pil_image is not None:
            dims = f"{self.current_pil_image.width} x {self.current_pil_image.height}px"
        else:
            dims = "Unknown size"
        self.detail_label.configure(
            text=f"{dims}  |  {round(self.current_zoom * 100)}%  |  {current}/{total}"
        )

    def _fit_zoom_for_image(self, image_width: int, image_height: int) -> float:
        canvas_w, canvas_h = self._viewer_bounds()
        available_w = max(canvas_w - 60, 120)
        available_h = max(canvas_h - 60, 120)
        return min(available_w / max(image_width, 1), available_h / max(image_height, 1), 1.0)

    def _load_image(self, path: Path) -> None:
        if Image:
            self.current_pil_image = Image.open(path)
            self.fit_zoom = self._fit_zoom_for_image(*self.current_pil_image.size)
            self.current_zoom = self.fit_zoom
            self.pan_x = 0.0
            self.pan_y = 0.0
            self._update_zoom_label()
            self._update_detail_label()
            return

        self.current_pil_image = None
        self.fit_zoom = 1.0
        self.current_zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._update_zoom_label()
        self._update_detail_label()

    def _thumbnail_image(self, path: Path) -> object | None:
        if Image and ImageTk:
            image = Image.open(path)
            image.thumbnail((84, 84), Image.LANCZOS)
            return ImageTk.PhotoImage(image)
        return None

    def _select_index(self, index: int) -> None:
        if not self.images:
            return
        self.index = index % len(self.images)
        self._load_image(self.current_path())
        self.counter_label.configure(text=f"{self.index + 1} / {len(self.images)}")
        self.path_label.configure(text=str(self.current_path()))
        self._update_detail_label()
        self._render_thumbnails()
        self._render_current_image()

    def _scroll_thumbnail_into_view(self, index: int) -> None:
        self.root.update_idletasks()
        children = self.thumbnail_strip.winfo_children()
        if index < 0 or index >= len(children):
            return
        child = children[index]
        total_width = max(self.thumbnail_strip.winfo_width(), 1)
        visible_width = max(self.thumbnail_canvas.winfo_width(), 1)
        center = child.winfo_x() + child.winfo_width() / 2
        target = max(center - visible_width / 2, 0)
        max_offset = max(total_width - visible_width, 1)
        self.thumbnail_canvas.xview_moveto(min(target / max_offset, 1.0))

    def _render_thumbnails(self) -> None:
        for child in self.thumbnail_strip.winfo_children():
            child.destroy()
        self.thumbnail_photo_refs = []

        for idx, path in enumerate(self.images):
            selected = idx == self.index
            frame = tk.Frame(
                self.thumbnail_strip,
                bg=ACCENT_SOFT if selected else MUTED_BG,
                highlightbackground=ACCENT if selected else BORDER,
                highlightthickness=2 if selected else 1,
                padx=6,
                pady=6,
            )
            frame.pack(side="left", padx=(0, 10), pady=8)

            thumb = self._thumbnail_image(path)
            if thumb is not None:
                label = tk.Label(frame, image=thumb, bg=frame.cget("bg"), cursor="hand2")
                self.thumbnail_photo_refs.append(thumb)
            else:
                label = tk.Label(
                    frame,
                    text=path.name[:10],
                    bg=frame.cget("bg"),
                    fg=TEXT_SECONDARY,
                    width=12,
                    height=5,
                    cursor="hand2",
                )
            label.pack()
            meta = tk.Label(
                frame,
                text=str(idx + 1),
                bg=frame.cget("bg"),
                fg=TEXT_PRIMARY if selected else TEXT_SECONDARY,
                font=("Segoe UI", 9, "bold"),
            )
            meta.pack(pady=(6, 0))

            for widget in (frame, label, meta):
                widget.bind("<Button-1>", lambda _event, target=idx: self._select_index(target))

        self._on_thumbnail_configure(tk.Event())
        self._scroll_thumbnail_into_view(self.index)

    def reset_view(self) -> None:
        if self.current_pil_image is None and not self.images:
            return
        if self.current_pil_image is not None:
            self.fit_zoom = self._fit_zoom_for_image(*self.current_pil_image.size)
            self.current_zoom = self.fit_zoom
        else:
            self.current_zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._update_zoom_label()
        self._update_detail_label()
        self._render_current_image()

    def _clamp_pan(self, image_w: float, image_h: float) -> None:
        canvas_w, canvas_h = self._viewer_bounds()
        max_x = max((image_w - canvas_w) / 2, 0)
        max_y = max((image_h - canvas_h) / 2, 0)
        self.pan_x = max(min(self.pan_x, max_x), -max_x)
        self.pan_y = max(min(self.pan_y, max_y), -max_y)

    def _zoom_at(self, factor: float, event_x: float | None = None, event_y: float | None = None) -> None:
        if self.current_pil_image is None:
            return
        old_zoom = self.current_zoom
        new_zoom = max(self.fit_zoom * 0.5, min(self.current_zoom * factor, 8.0))
        if abs(new_zoom - old_zoom) < 0.0001:
            return

        canvas_w, canvas_h = self._viewer_bounds()
        cursor_x = event_x if event_x is not None else canvas_w / 2
        cursor_y = event_y if event_y is not None else canvas_h / 2

        image_x = cursor_x - (canvas_w / 2 + self.pan_x)
        image_y = cursor_y - (canvas_h / 2 + self.pan_y)
        ratio = new_zoom / old_zoom
        self.pan_x = cursor_x - canvas_w / 2 - image_x * ratio
        self.pan_y = cursor_y - canvas_h / 2 - image_y * ratio
        self.current_zoom = new_zoom
        self._clamp_pan(
            self.current_pil_image.width * new_zoom,
            self.current_pil_image.height * new_zoom,
        )
        self._update_zoom_label()
        self._update_detail_label()
        self._render_current_image()

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        direction = 1 if getattr(event, "delta", 0) > 0 else -1
        factor = 1.12 if direction > 0 else 1 / 1.12
        self._zoom_at(factor, float(event.x), float(event.y))

    def _on_mousewheel_linux(self, event: tk.Event[tk.Misc], direction: int) -> None:
        factor = 1.12 if direction > 0 else 1 / 1.12
        self._zoom_at(factor, float(event.x), float(event.y))

    def _toggle_fit_actual(self, _event: tk.Event[tk.Misc]) -> None:
        if self.current_pil_image is None:
            return
        if abs(self.current_zoom - self.fit_zoom) < 0.02:
            self.current_zoom = 1.0
        else:
            self.current_zoom = self.fit_zoom
            self.pan_x = 0.0
            self.pan_y = 0.0
        self._update_zoom_label()
        self._update_detail_label()
        self._render_current_image()

    def _start_pan(self, event: tk.Event[tk.Misc]) -> None:
        self._drag_origin = (event.x, event.y)
        self._pan_origin = (self.pan_x, self.pan_y)
        self.viewer.configure(cursor="fleur")

    def _move_pan(self, event: tk.Event[tk.Misc]) -> None:
        if self._drag_origin is None or self._pan_origin is None or self.current_pil_image is None:
            return
        start_x, start_y = self._drag_origin
        base_pan_x, base_pan_y = self._pan_origin
        self.pan_x = base_pan_x + (event.x - start_x)
        self.pan_y = base_pan_y + (event.y - start_y)
        self._clamp_pan(
            self.current_pil_image.width * self.current_zoom,
            self.current_pil_image.height * self.current_zoom,
        )
        self._render_current_image()

    def _end_pan(self, _event: tk.Event[tk.Misc]) -> None:
        self._drag_origin = None
        self._pan_origin = None
        self.viewer.configure(cursor="")

    def _render_current_image(self) -> None:
        self.viewer.delete("all")
        if not self.images:
            self.viewer.create_text(
                self.viewer.winfo_width() / 2,
                self.viewer.winfo_height() / 2,
                text="No image loaded",
                fill=TEXT_SECONDARY,
                font=("Segoe UI", 16),
            )
            return

        current = self.images[self.index]
        try:
            if Image and ImageTk:
                if self.current_pil_image is None:
                    self._load_image(current)
                assert self.current_pil_image is not None
                scaled_w = max(int(self.current_pil_image.width * self.current_zoom), 1)
                scaled_h = max(int(self.current_pil_image.height * self.current_zoom), 1)
                resized = self.current_pil_image.resize((scaled_w, scaled_h), Image.LANCZOS)
                self.photo = ImageTk.PhotoImage(resized)
            else:
                self.photo = tk.PhotoImage(file=str(current))
        except Exception as exc:  # noqa: BLE001
            self.viewer.create_text(
                self.viewer.winfo_width() / 2,
                self.viewer.winfo_height() / 2,
                text=f"Unable to open image\n{exc}",
                fill=TEXT_SECONDARY,
                font=("Segoe UI", 14),
            )
            return

        canvas_w, canvas_h = self._viewer_bounds()
        image_x = canvas_w / 2 + self.pan_x
        image_y = canvas_h / 2 + self.pan_y
        self.viewer.create_image(image_x, image_y, image=self.photo)
        self.viewer.create_text(
            18,
            18,
            anchor="nw",
            text="Scroll to zoom | Drag to pan | Double-click to toggle fit/100% | 0 to fit",
            fill=TEXT_SECONDARY,
            font=("Segoe UI", 10),
        )

    def apply_payload(self, payload: dict[str, object]) -> None:
        images = payload.get("images")
        if not isinstance(images, list) or not images:
            return

        resolved = [Path(str(item)).expanduser().resolve() for item in images]
        fresh_images = [path for path in resolved if path.exists()]
        if not fresh_images:
            return

        existing = list(self.images)
        for path in fresh_images:
            if path in existing:
                existing.remove(path)
            existing.append(path)
        self.images = existing[-MAX_HISTORY:]
        self.index = max(len(self.images) - len(fresh_images), 0)
        self._load_image(self.images[self.index])

        self.root.title(SKILL_NAME)
        self.window_title.configure(text=SKILL_NAME)
        current_position = self.index + 1
        total = len(self.images)
        self.counter_label.configure(text=f"{current_position} / {total}")
        self.sub_label.configure(text="Preview and download the latest generated result")
        self.path_label.configure(text=str(self.images[self.index]))
        updated_at = str(payload.get("updated_at") or "").strip()
        status = "Updated with the latest generation"
        if updated_at:
            status = f"{status} | {updated_at}"
        self.status_label.configure(text=status)
        self._update_detail_label()
        self.prev_button.set_disabled(len(self.images) <= 1)
        self.next_button.set_disabled(len(self.images) <= 1)
        self.root.deiconify()
        self.root.lift()
        self.root.after(50, lambda: self.root.attributes("-topmost", True))
        self.root.after(180, lambda: self.root.attributes("-topmost", False))
        self._render_thumbnails()
        self._render_current_image()

    def current_path(self) -> Path:
        return self.images[self.index]

    def show_previous(self) -> None:
        if len(self.images) <= 1:
            return
        self._select_index(self.index - 1)

    def show_next(self) -> None:
        if len(self.images) <= 1:
            return
        self._select_index(self.index + 1)

    def save_as(self) -> None:
        if not self.images:
            return
        source = self.current_path()
        target = filedialog.asksaveasfilename(
            title="Download Image",
            initialfile=source.name,
            defaultextension=source.suffix,
            filetypes=[
                ("PNG image", "*.png"),
                ("JPEG image", "*.jpg *.jpeg"),
                ("WebP image", "*.webp"),
                ("All files", "*.*"),
            ],
        )
        if not target:
            return
        shutil.copy2(source, target)
        messagebox.showinfo(SKILL_NAME, f"Saved to:\n{target}")

    def open_folder(self) -> None:
        if not self.images:
            return
        folder = self.current_path().parent
        if sys.platform.startswith("win"):
            os.startfile(folder)  # type: ignore[attr-defined]
            return
        subprocess.Popen(["xdg-open", str(folder)])

    def copy_path(self) -> None:
        if not self.images:
            return
        source = str(self.current_path())
        self.root.clipboard_clear()
        self.root.clipboard_append(source)
        self.root.update()
        self.status_label.configure(text="Current image path copied to clipboard")


def main() -> int:
    args = parse_args()
    payload = normalize_payload(args.images, args.title)

    if try_send_update(payload):
        return 0

    updates: "queue.Queue[dict[str, object]]" = queue.Queue()
    server = SingletonServer(updates)
    server.start()

    root = tk.Tk()
    PreviewApp(root, payload, updates)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
