"""Site plan: arrange designed buildings on a map's baseplate.

The building editor answers "what does this house look like". This answers
"where does it go". They are deliberately separate windows: a design carries no
position, because where a house sits is the map's business, not the house's.

Saves the layout file the game reads WHEN IT STARTS, so the loop is arrange
here, save, launch the game. No rebuilding anything.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from . import geometry as geo
from .model import Design

BG = "#141a13"
GRID = "#22301f"
GRID_MAJOR = "#3d5438"
PLATE = "#2f6b25"
EDGE = "#a8332c"
TEXT = "#d8d2b8"
SELECTED = "#f0d060"
MARKER = "#6f7f6a"

# The Baseplate, in studs. Keep PLATE_HALF_UNITS in step with the `half` local
# in tools/build_scenes.gd's _build_world_baseplate() -- it is the one number
# that decides how big the map is, and if the two disagree this editor will
# happily place buildings off the edge of the world.
PLATE_HALF_UNITS = 300.0
PLATE_HALF_STUDS = int(PLATE_HALF_UNITS / geo.STUD)
# spawns sit 32 units in from each edge (see the spawn ring in the same builder)
SPAWN_INSET_STUDS = int((PLATE_HALF_UNITS - 32.0) / geo.STUD)

ROTATIONS = [0, 90, 180, 270]


def rotated_extent(design: Design, rotation: int) -> tuple[int, int]:
    """Footprint size in studs after turning it. 90 and 270 swap the axes."""
    xs = [p[0] for p in design.footprint]
    ys = [p[1] for p in design.footprint]
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    return (d, w) if rotation % 180 else (w, d)


class LayoutApp:
    def __init__(self, root: tk.Tk, designs_dir: Path, layout_path: Path):
        self.root = root
        self.designs_dir = designs_dir
        self.layout_path = layout_path
        self.designs: dict[str, Design] = {}
        self.placed: list[dict] = []
        self.selected: int | None = None
        self.scale = 0.55  # pixels per stud; the plate is ~900 studs across
        self.origin = [520.0, 380.0]
        self.drag_from: tuple[int, int] | None = None

        root.title("Lego House Maker - site plan")
        root.configure(bg=BG)
        self._build_ui()
        self._bind()
        self.reload_designs()
        self.load_layout()
        self.redraw()

    # --- ui ---------------------------------------------------------------
    def _build_ui(self) -> None:
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=8)

        tk.Label(bar, text="DESIGNS", bg=BG, fg=TEXT).pack(anchor="w")
        self.design_list = tk.Listbox(bar, bg=GRID, fg=TEXT, width=22, height=12,
                                      selectbackground=PLATE, highlightthickness=0)
        self.design_list.pack(anchor="w")
        tk.Label(bar, text="click the plate to place", bg=BG, fg=GRID_MAJOR,
                 font=("TkDefaultFont", 8)).pack(anchor="w")

        tk.Label(bar, text="", bg=BG).pack()
        tk.Label(bar, text="SELECTED BUILDING", bg=BG, fg=TEXT).pack(anchor="w")
        self.sel_label = tk.Label(bar, text="none", bg=BG, fg=TEXT, justify="left")
        self.sel_label.pack(anchor="w")
        row = tk.Frame(bar, bg=BG)
        row.pack(anchor="w")
        tk.Button(row, text="Rotate", command=self.rotate_selected).pack(side=tk.LEFT)
        tk.Button(row, text="Delete", command=self.delete_selected).pack(side=tk.LEFT)
        tk.Label(bar, text="drag to move, R rotates, Del removes", bg=BG,
                 fg=GRID_MAJOR, font=("TkDefaultFont", 8)).pack(anchor="w")

        tk.Label(bar, text="", bg=BG).pack()
        for label, cmd in [
            ("Reload designs", self.reload_designs_and_draw),
            ("Open layout...", self.pick_layout),
            ("Save layout", self.save_layout),
        ]:
            tk.Button(bar, text=label, width=18, command=cmd).pack(anchor="w", pady=1)
        self.path_label = tk.Label(bar, text="", bg=BG, fg=GRID_MAJOR,
                                   font=("TkDefaultFont", 8), wraplength=150, justify="left")
        self.path_label.pack(anchor="w")

        right = tk.Frame(self.root, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(right, bg=BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(right, text="", bg=BG, fg=TEXT, anchor="w")
        self.status.pack(fill=tk.X)

    def _bind(self) -> None:
        c = self.canvas
        c.bind("<Button-1>", self.on_click)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", lambda _e: setattr(self, "drag_from", None))
        c.bind("<Motion>", self.on_move)
        c.bind("<Button-2>", lambda e: setattr(self, "_pan", (e.x, e.y)))
        c.bind("<B2-Motion>", self.on_pan)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Button-4>", lambda e: self.on_wheel(e, 1))
        c.bind("<Button-5>", lambda e: self.on_wheel(e, -1))
        c.bind("<Configure>", lambda _e: self.redraw())
        self.root.bind("r", lambda _e: self.rotate_selected())
        self.root.bind("<Delete>", lambda _e: self.delete_selected())
        self.root.bind("<Control-s>", lambda _e: self.save_layout())

    # --- data -------------------------------------------------------------
    def reload_designs(self) -> None:
        self.designs.clear()
        self.design_list.delete(0, tk.END)
        if not self.designs_dir.is_dir():
            return
        for path in sorted(self.designs_dir.glob("*.json")):
            try:
                self.designs[path.name] = Design.load(path)
            except Exception:  # noqa: BLE001 - a bad file should not stop the rest
                continue
            self.design_list.insert(tk.END, path.name)
        if self.design_list.size():
            self.design_list.selection_set(0)

    def reload_designs_and_draw(self) -> None:
        self.reload_designs()
        self.redraw()

    def load_layout(self) -> None:
        self.placed = []
        if self.layout_path.exists():
            try:
                data = json.loads(self.layout_path.read_text())
                self.placed = list(data.get("buildings", []))
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Could not read layout", str(exc))
        self.path_label.config(text=str(self.layout_path))

    def pick_layout(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Layout", "*.json")])
        if path:
            self.layout_path = Path(path)
            self.load_layout()
            self.redraw()

    def save_layout(self) -> None:
        data = {"map": self.layout_path.stem,
                "comment": "Buildings on this map. Read WHEN THE GAME STARTS, so "
                           "editing this and relaunching is all it takes -- the map "
                           "does not need rebuilding. Positions are in STUDS from the "
                           "middle of the plate.",
                "buildings": self.placed}
        self.layout_path.write_text(json.dumps(data, indent=2) + "\n")
        self.status.config(text=f"saved {len(self.placed)} building(s) to {self.layout_path}")

    # --- interaction ------------------------------------------------------
    def world(self, sx, sy) -> tuple[int, int]:
        return (int(round((sx - self.origin[0]) / self.scale)),
                int(round((sy - self.origin[1]) / self.scale)))

    def screen(self, x, y) -> tuple[float, float]:
        return (self.origin[0] + x * self.scale, self.origin[1] + y * self.scale)

    def hit_test(self, x: int, y: int) -> int | None:
        """Topmost placed building whose footprint box contains (x, y)."""
        for i in range(len(self.placed) - 1, -1, -1):
            entry = self.placed[i]
            design = self.designs.get(entry.get("design", ""))
            if design is None:
                continue
            w, d = rotated_extent(design, int(entry.get("rotation", 0)))
            cx, cy = entry.get("at_studs", [0, 0])
            if abs(x - cx) <= w / 2 and abs(y - cy) <= d / 2:
                return i
        return None

    def on_click(self, event) -> None:
        x, y = self.world(event.x, event.y)
        hit = self.hit_test(x, y)
        if hit is not None:
            self.selected = hit
            self.drag_from = (x, y)
        else:
            sel = self.design_list.curselection()
            if not sel:
                self.status.config(text="pick a design on the left first")
                return
            name = self.design_list.get(sel[0])
            self.placed.append({"design": name, "at_studs": [x, y], "rotation": 0})
            self.selected = len(self.placed) - 1
            self.status.config(text=f"placed {name} at {x}, {y} studs")
        self.redraw()

    def on_drag(self, event) -> None:
        if self.selected is None or self.drag_from is None:
            return
        x, y = self.world(event.x, event.y)
        dx, dy = x - self.drag_from[0], y - self.drag_from[1]
        at = self.placed[self.selected]["at_studs"]
        self.placed[self.selected]["at_studs"] = [at[0] + dx, at[1] + dy]
        self.drag_from = (x, y)
        self.redraw()

    def on_pan(self, event) -> None:
        self.origin[0] += event.x - self._pan[0]
        self.origin[1] += event.y - self._pan[1]
        self._pan = (event.x, event.y)
        self.redraw()

    def on_wheel(self, event, direction=None) -> None:
        step = direction if direction is not None else (1 if event.delta > 0 else -1)
        self.scale = max(0.15, min(6.0, self.scale * (1.15 if step > 0 else 1 / 1.15)))
        self.redraw()

    def on_move(self, event) -> None:
        x, y = self.world(event.x, event.y)
        self.status.config(text=f"{x}, {y} studs    {len(self.placed)} building(s) placed")

    def rotate_selected(self) -> None:
        if self.selected is None:
            return
        entry = self.placed[self.selected]
        entry["rotation"] = ROTATIONS[(ROTATIONS.index(int(entry.get("rotation", 0))) + 1) % 4]
        self.redraw()

    def delete_selected(self) -> None:
        if self.selected is None:
            return
        gone = self.placed.pop(self.selected)
        self.selected = None
        self.status.config(text=f"removed {gone['design']}")
        self.redraw()

    # --- drawing ----------------------------------------------------------
    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        half = PLATE_HALF_STUDS
        c.create_rectangle(*self.screen(-half, -half), *self.screen(half, half),
                           fill=PLATE, outline=EDGE, width=3)
        step = 100
        for v in range(-half + step, half, step):
            c.create_line(*self.screen(v, -half), *self.screen(v, half), fill=GRID)
            c.create_line(*self.screen(-half, v), *self.screen(half, v), fill=GRID)
        # the fixed furniture, so you can place around it
        for label, x, y in [("hill", 0, 0),
                            ("green spawn", 0, SPAWN_INSET_STUDS),
                            ("tan spawn", 0, -SPAWN_INSET_STUDS)]:
            sx, sy = self.screen(x, y)
            c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, outline=MARKER)
            c.create_text(sx, sy - 14, text=label, fill=MARKER, font=("TkDefaultFont", 8))
        for i, entry in enumerate(self.placed):
            design = self.designs.get(entry.get("design", ""))
            cx, cy = entry.get("at_studs", [0, 0])
            rot = int(entry.get("rotation", 0))
            if design is None:
                sx, sy = self.screen(cx, cy)
                c.create_text(sx, sy, text=f"?{entry.get('design')}", fill=EDGE)
                continue
            w, d = rotated_extent(design, rot)
            colour = geo.COLOURS.get(design.colour, (0.7, 0.7, 0.7))
            fill = "#%02x%02x%02x" % tuple(int(v * 255) for v in colour)
            outline = SELECTED if i == self.selected else TEXT
            c.create_rectangle(*self.screen(cx - w / 2, cy - d / 2),
                               *self.screen(cx + w / 2, cy + d / 2),
                               fill=fill, outline=outline, width=3 if i == self.selected else 1)
            sx, sy = self.screen(cx, cy)
            c.create_text(sx, sy, text=f"{entry['design']}\n{rot}°", fill=TEXT,
                          font=("TkDefaultFont", 8))
        if self.selected is not None and self.selected < len(self.placed):
            e = self.placed[self.selected]
            self.sel_label.config(text=f"{e['design']}\nat {e['at_studs'][0]}, {e['at_studs'][1]}\n{e['rotation']} degrees")
        else:
            self.sel_label.config(text="none")


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = argv if argv is not None else sys.argv[1:]
    designs_dir = Path(argv[0]) if argv else Path.home() / "army" / "designs"
    layout_path = Path(argv[1]) if len(argv) > 1 else designs_dir / "layouts" / "baseplate.json"
    root = tk.Tk()
    root.geometry("1180x800")
    LayoutApp(root, designs_dir, layout_path)
    root.mainloop()
    return 0
