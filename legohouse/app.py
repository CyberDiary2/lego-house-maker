"""The plan-view editor: a tkinter canvas you draw a building on.

Plain tkinter on purpose. It ships with Python, so the app runs with no install
step at all, which matters for a tool that mostly gets opened, used for ten
minutes and closed.

Screen space is pixels, world space is STUDS with +y running "south" (down the
screen). The game's own +z is the same direction, so a plan drawn here lands in
the world the way it looks here.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from . import geometry as geo
from .model import Design, Storey, Opening, InteriorWall, Ramp

GRID = "#22301f"
GRID_MAJOR = "#3d5438"
BG = "#141a13"
FOOTPRINT = "#d8d2b8"
FOOTPRINT_DRAFT = "#8fbf6a"
GHOST = "#2f3a2c"
DOOR = "#e8b23a"
WINDOW = "#5fa8e8"
INTERIOR = "#c08a4a"
RAMP = "#b06fd0"
TEXT = "#d8d2b8"

DIRECTION_VECTORS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}


class DesignerApp:
    def __init__(self, root: tk.Tk, design: Design | None = None, path: Path | None = None):
        self.root = root
        self.design = design or Design()
        self.path = path
        self.storey_index = 0
        self.tool = tk.StringVar(value="footprint")
        self.ramp_dir = tk.StringVar(value="n")
        self.scale = 6.0  # pixels per stud
        self.origin = [80.0, 80.0]  # screen position of world (0,0)
        self.draft: list[tuple[int, int]] = []  # footprint being drawn
        self.drag_start: tuple[int, int] | None = None
        self.drag_now: tuple[int, int] | None = None

        root.title("Lego House Maker")
        root.configure(bg=BG)
        self._build_ui()
        self._bind()
        self.redraw()

    # --- layout -----------------------------------------------------------
    def _build_ui(self) -> None:
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=8)

        tk.Label(bar, text="TOOL", bg=BG, fg=TEXT).pack(anchor="w")
        for value, label in [
            ("footprint", "Footprint"),
            ("door", "Doorway"),
            ("window", "Window"),
            ("interior", "Interior wall"),
            ("ramp", "Ramp up"),
            ("erase", "Erase"),
        ]:
            tk.Radiobutton(
                bar, text=label, value=value, variable=self.tool, bg=BG, fg=TEXT,
                selectcolor=GRID, activebackground=BG, activeforeground=TEXT,
                anchor="w", width=14, command=self.redraw,
            ).pack(anchor="w")
        self._hint(bar, "door 12 studs wide")
        self._hint(bar, "window 8 wide, sill 4, tall 4")
        self._hint(bar, "footprint 70 x 56 is typical")

        tk.Label(bar, text="", bg=BG).pack()
        tk.Label(bar, text="RAMP CLIMBS", bg=BG, fg=TEXT).pack(anchor="w")
        ttk.Combobox(
            bar, textvariable=self.ramp_dir, width=12, state="readonly",
            values=["n", "s", "e", "w"],
        ).pack(anchor="w")
        self._hint(bar, "ramp 12 studs wide")
        self.ramp_hint = tk.Label(bar, text="", bg=BG, fg=GRID_MAJOR, justify="left")
        self.ramp_hint.pack(anchor="w")

        tk.Label(bar, text="", bg=BG).pack()
        tk.Label(bar, text="STOREY", bg=BG, fg=TEXT).pack(anchor="w")
        self.storey_label = tk.Label(bar, text="1 of 1", bg=BG, fg=TEXT)
        self.storey_label.pack(anchor="w")
        self._hint(bar, "2 is typical; each one above")
        self._hint(bar, "the first needs a ramp")
        row = tk.Frame(bar, bg=BG)
        row.pack(anchor="w")
        tk.Button(row, text="<", width=2, command=lambda: self.switch_storey(-1)).pack(side=tk.LEFT)
        tk.Button(row, text=">", width=2, command=lambda: self.switch_storey(1)).pack(side=tk.LEFT)
        tk.Button(row, text="Add", command=self.add_storey).pack(side=tk.LEFT)
        tk.Button(row, text="Del", command=self.remove_storey).pack(side=tk.LEFT)

        tk.Label(bar, text="", bg=BG).pack()
        tk.Label(bar, text="WALL HEIGHT (courses)", bg=BG, fg=TEXT).pack(anchor="w")
        self.height_var = tk.IntVar(value=self.storey.wall_courses)
        tk.Spinbox(
            bar, from_=1, to=40, textvariable=self.height_var, width=6,
            command=self.apply_height,
        ).pack(anchor="w")
        self._hint(bar, "default 10 = one storey")
        self.height_hint = tk.Label(bar, text="", bg=BG, fg=GRID_MAJOR)
        self.height_hint.pack(anchor="w")

        tk.Label(bar, text="", bg=BG).pack()
        tk.Label(bar, text="COLOUR", bg=BG, fg=TEXT).pack(anchor="w")
        self.colour_var = tk.StringVar(value=self.design.colour)
        colour_box = ttk.Combobox(
            bar, textvariable=self.colour_var, width=12, state="readonly",
            values=sorted(geo.COLOURS),
        )
        colour_box.pack(anchor="w")
        colour_box.bind("<<ComboboxSelected>>", lambda _e: self.apply_colour())

        self.roof_var = tk.BooleanVar(value=self.design.roof)
        tk.Checkbutton(
            bar, text="Studded roof", variable=self.roof_var, bg=BG, fg=TEXT,
            selectcolor=GRID, activebackground=BG, activeforeground=TEXT,
            command=self.apply_roof,
        ).pack(anchor="w")

        tk.Label(bar, text="", bg=BG).pack()
        for label, cmd in [
            ("New", self.new_design),
            ("Open...", self.open_design),
            ("Save", self.save_design),
            ("Save as...", self.save_design_as),
            ("Check design", self.show_problems),
            ("3D preview", self.preview),
        ]:
            tk.Button(bar, text=label, width=14, command=cmd).pack(anchor="w", pady=1)

        right = tk.Frame(self.root, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(right, bg=BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(right, text="", bg=BG, fg=TEXT, anchor="w")
        self.status.pack(fill=tk.X)

    def _hint(self, parent: tk.Widget, text: str) -> None:
        """A dim one-liner under a control saying what a normal value is.

        Worth the screen space: studs and courses are unfamiliar units, and
        without a reference every field is a guess. The numbers are the ones the
        game's own buildings use -- see geometry.DEFAULTS.
        """
        tk.Label(parent, text=text, bg=BG, fg=GRID_MAJOR,
                 font=("TkDefaultFont", 8)).pack(anchor="w")

    def _bind(self) -> None:
        c = self.canvas
        c.bind("<Button-1>", self.on_click)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Motion>", self.on_move)
        c.bind("<Button-3>", self.on_right_click)
        c.bind("<Button-2>", lambda e: self._pan_start(e))
        c.bind("<B2-Motion>", self._pan_move)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Button-4>", lambda e: self.on_wheel(e, 1))
        c.bind("<Button-5>", lambda e: self.on_wheel(e, -1))
        c.bind("<Configure>", lambda _e: self.redraw())
        self.root.bind("<Escape>", lambda _e: self.cancel_draft())
        self.root.bind("<Control-s>", lambda _e: self.save_design())
        self.root.bind("<Control-z>", lambda _e: self.undo_point())

    # --- state helpers ----------------------------------------------------
    @property
    def storey(self) -> Storey:
        return self.design.storeys[self.storey_index]

    def world(self, sx: float, sy: float) -> tuple[int, int]:
        """Screen pixels -> nearest stud."""
        return (
            int(round((sx - self.origin[0]) / self.scale)),
            int(round((sy - self.origin[1]) / self.scale)),
        )

    def screen(self, x: float, y: float) -> tuple[float, float]:
        return (self.origin[0] + x * self.scale, self.origin[1] + y * self.scale)

    # --- tools ------------------------------------------------------------
    def on_click(self, event) -> None:
        x, y = self.world(event.x, event.y)
        tool = self.tool.get()
        if tool == "footprint":
            self.place_footprint_point(x, y)
        elif tool in ("door", "window"):
            self.place_opening(x, y, tool)
        elif tool == "interior":
            self.drag_start = (x, y)
            self.drag_now = (x, y)
        elif tool == "ramp":
            self.place_ramp(x, y)
        elif tool == "erase":
            self.erase_at(x, y)
        self.redraw()

    def on_drag(self, event) -> None:
        if self.tool.get() == "interior" and self.drag_start:
            self.drag_now = self._axis_lock(self.drag_start, self.world(event.x, event.y))
            self.redraw()

    def on_release(self, event) -> None:
        if self.tool.get() == "interior" and self.drag_start and self.drag_now:
            if self.drag_start != self.drag_now:
                self.storey.interior_walls.append(
                    InteriorWall(a=self.drag_start, b=self.drag_now)
                )
            self.drag_start = None
            self.drag_now = None
            self.redraw()

    def on_right_click(self, _event) -> None:
        if self.tool.get() == "footprint":
            self.undo_point()

    def _axis_lock(self, a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
        """Force b onto the axis from a that it has travelled furthest along.

        Every wall in a design has to be axis aligned, so rather than reject a
        sloppy drag this snaps it to what the user obviously meant.
        """
        dx, dy = b[0] - a[0], b[1] - a[1]
        if abs(dx) >= abs(dy):
            return (b[0], a[1])
        return (a[0], b[1])

    def place_footprint_point(self, x: float, y: float) -> None:
        point = (int(x), int(y))
        if not self.draft:
            self.design.footprint = []
            self.draft = [point]
            return
        # closing the loop: click back near the start
        if len(self.draft) >= 3 and abs(point[0] - self.draft[0][0]) <= 1 and abs(point[1] - self.draft[0][1]) <= 1:
            closed = self._closed_footprint(self.draft)
            if closed and geo.is_rectilinear(closed):
                self.design.footprint = closed
                self.draft = []
                self.status.config(text=f"footprint closed: {len(closed)} walls")
            else:
                self.status.config(text="that would not close into a rectilinear shape")
            return
        self.draft.append(self._axis_lock(self.draft[-1], point))

    def _closed_footprint(self, draft: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Add the final corner that squares the loop back to the start, if needed."""
        pts = list(draft)
        first, last = pts[0], pts[-1]
        if first == last:
            pts.pop()
            return pts
        if first[0] == last[0] or first[1] == last[1]:
            return pts
        # one dogleg gets us home while keeping every wall axis aligned
        pts.append((first[0], last[1]))
        return pts

    def place_opening(self, x: float, y: float, kind: str) -> None:
        hit = self._nearest_wall(x, y)
        if hit is None:
            self.status.config(text="click on a wall to put an opening in it")
            return
        wall_index, along, span = hit
        width = 12 if kind == "door" else 8
        start = max(0, min(int(along) - width // 2, span - width))
        if span < width:
            self.status.config(text=f"wall {wall_index} is only {span} studs long")
            return
        if kind == "door":
            self.storey.openings.append(
                Opening(kind="door", wall=wall_index, from_studs=start,
                        width_studs=width, height_courses=min(8, self.storey.wall_courses))
            )
        else:
            self.storey.openings.append(
                Opening(kind="window", wall=wall_index, from_studs=start, width_studs=width,
                        sill_courses=min(4, max(0, self.storey.wall_courses - 2)),
                        height_courses=min(4, self.storey.wall_courses))
            )
        self.status.config(text=f"{kind} on wall {wall_index} at {start} studs")

    def _nearest_wall(self, x: float, y: float, tolerance: float = 2.5):
        """(wall index, distance along it, its length) for the wall nearest a point."""
        best = None
        for i, ((x1, y1), (x2, y2)) in enumerate(geo.edges(self.design.footprint)):
            if x1 == x2:
                if min(y1, y2) - tolerance <= y <= max(y1, y2) + tolerance:
                    dist = abs(x - x1)
                    along = abs(y - y1)
                    if dist <= tolerance and (best is None or dist < best[0]):
                        best = (dist, i, along, geo.edge_length_studs(((x1, y1), (x2, y2))))
            else:
                if min(x1, x2) - tolerance <= x <= max(x1, x2) + tolerance:
                    dist = abs(y - y1)
                    along = abs(x - x1)
                    if dist <= tolerance and (best is None or dist < best[0]):
                        best = (dist, i, along, geo.edge_length_studs(((x1, y1), (x2, y2))))
        if best is None:
            return None
        return best[1], best[2], best[3]

    def place_ramp(self, x: float, y: float) -> None:
        if self.storey_index >= len(self.design.storeys) - 1:
            self.status.config(text="top storey: add a storey above before placing a ramp")
            return
        ramp = Ramp(at=(int(x), int(y)), direction=self.ramp_dir.get())
        problems = ramp.validate(self.design, self.storey_index)
        if problems:
            self.status.config(text=problems[0])
            return
        self.storey.ramps.append(ramp)
        run = geo.ramp_run_studs(self.storey.wall_courses)
        self.status.config(text=f"ramp climbing {ramp.direction} over {run} studs")

    def erase_at(self, x: float, y: float) -> None:
        hit = self._nearest_wall(x, y)
        if hit is not None:
            wall_index, along, _span = hit
            for opening in list(self.storey.openings):
                if opening.wall == wall_index and opening.from_studs <= along <= opening.from_studs + opening.width_studs:
                    self.storey.openings.remove(opening)
                    self.status.config(text=f"removed {opening.kind}")
                    return
        for wall in list(self.storey.interior_walls):
            if self._near_segment(x, y, wall.a, wall.b):
                self.storey.interior_walls.remove(wall)
                self.status.config(text="removed interior wall")
                return
        for ramp in list(self.storey.ramps):
            if abs(ramp.at[0] - x) <= 2 and abs(ramp.at[1] - y) <= 2:
                self.storey.ramps.remove(ramp)
                self.status.config(text="removed ramp")
                return
        self.status.config(text="nothing to erase there")

    def _near_segment(self, x, y, a, b, tolerance=1.5) -> bool:
        if a[0] == b[0]:
            return abs(x - a[0]) <= tolerance and min(a[1], b[1]) <= y <= max(a[1], b[1])
        return abs(y - a[1]) <= tolerance and min(a[0], b[0]) <= x <= max(a[0], b[0])

    def undo_point(self) -> None:
        if self.draft:
            self.draft.pop()
            self.redraw()

    def cancel_draft(self) -> None:
        self.draft = []
        self.drag_start = None
        self.redraw()

    # --- storey / property controls ---------------------------------------
    def switch_storey(self, delta: int) -> None:
        self.storey_index = max(0, min(self.storey_index + delta, len(self.design.storeys) - 1))
        self.height_var.set(self.storey.wall_courses)
        self.redraw()

    def add_storey(self) -> None:
        self.design.storeys.insert(self.storey_index + 1, Storey(wall_courses=self.storey.wall_courses))
        self.storey_index += 1
        self.height_var.set(self.storey.wall_courses)
        self.redraw()

    def remove_storey(self) -> None:
        if len(self.design.storeys) == 1:
            self.status.config(text="a building needs at least one storey")
            return
        self.design.storeys.pop(self.storey_index)
        self.storey_index = min(self.storey_index, len(self.design.storeys) - 1)
        self.height_var.set(self.storey.wall_courses)
        self.redraw()

    def apply_height(self) -> None:
        try:
            self.storey.wall_courses = max(1, int(self.height_var.get()))
        except (tk.TclError, ValueError):
            return
        self.redraw()

    def apply_colour(self) -> None:
        self.design.colour = self.colour_var.get()
        self.redraw()

    def apply_roof(self) -> None:
        self.design.roof = bool(self.roof_var.get())

    # --- view -------------------------------------------------------------
    def _pan_start(self, event) -> None:
        self._pan_from = (event.x, event.y)

    def _pan_move(self, event) -> None:
        dx = event.x - self._pan_from[0]
        dy = event.y - self._pan_from[1]
        self.origin[0] += dx
        self.origin[1] += dy
        self._pan_from = (event.x, event.y)
        self.redraw()

    def on_wheel(self, event, direction: int | None = None) -> None:
        step = direction if direction is not None else (1 if event.delta > 0 else -1)
        before = self.world(event.x, event.y)
        self.scale = max(1.5, min(40.0, self.scale * (1.15 if step > 0 else 1 / 1.15)))
        after = self.world(event.x, event.y)
        self.origin[0] += (after[0] - before[0]) * self.scale
        self.origin[1] += (after[1] - before[1]) * self.scale
        self.redraw()

    def on_move(self, event) -> None:
        x, y = self.world(event.x, event.y)
        courses = self.storey.wall_courses
        self.status.config(
            text=f"{x}, {y} studs    storey {self.storey_index + 1}/{len(self.design.storeys)}"
                 f"    wall {courses} courses ({geo.courses_to_units(courses):.2f} units)"
        )

    # --- drawing ----------------------------------------------------------
    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        self.storey_label.config(text=f"{self.storey_index + 1} of {len(self.design.storeys)}")
        courses = self.storey.wall_courses
        self.height_hint.config(text=f"= {geo.courses_to_units(courses):.2f} world units")
        self.ramp_hint.config(
            text=f"needs {geo.ramp_run_studs(courses)} studs of run\nto climb this storey")
        self._draw_grid()
        self._draw_footprint()
        self._draw_storey()
        self._draw_draft()

    def _draw_grid(self) -> None:
        c = self.canvas
        w = c.winfo_width() or 900
        h = c.winfo_height() or 700
        if self.scale >= 4:
            step = 1
        elif self.scale >= 2:
            step = 5
        else:
            step = 10
        x0, _ = self.world(0, 0)
        x1, _ = self.world(w, 0)
        _, y0 = self.world(0, 0)
        _, y1 = self.world(0, h)
        for x in range(x0 - 1, x1 + 2):
            if x % step:
                continue
            sx, _ = self.screen(x, 0)
            c.create_line(sx, 0, sx, h, fill=GRID_MAJOR if x % 10 == 0 else GRID)
        for y in range(y0 - 1, y1 + 2):
            if y % step:
                continue
            _, sy = self.screen(0, y)
            c.create_line(0, sy, w, sy, fill=GRID_MAJOR if y % 10 == 0 else GRID)

    def _draw_footprint(self) -> None:
        if len(self.design.footprint) < 3:
            return
        c = self.canvas
        pts = []
        for x, y in self.design.footprint:
            pts.extend(self.screen(x, y))
        c.create_polygon(pts, outline=FOOTPRINT, fill=GHOST, width=3)
        for i, ((x1, y1), (x2, y2)) in enumerate(geo.edges(self.design.footprint)):
            mx, my = self.screen((x1 + x2) / 2, (y1 + y2) / 2)
            c.create_text(mx, my, text=str(i), fill=GRID_MAJOR, font=("TkDefaultFont", 8))

    def _draw_storey(self) -> None:
        c = self.canvas
        walls = geo.edges(self.design.footprint)
        for opening in self.storey.openings:
            if opening.wall >= len(walls):
                continue
            (x1, y1), (x2, y2) = walls[opening.wall]
            dx = (x2 - x1) / max(1, geo.edge_length_studs(walls[opening.wall]))
            dy = (y2 - y1) / max(1, geo.edge_length_studs(walls[opening.wall]))
            ax = x1 + dx * opening.from_studs
            ay = y1 + dy * opening.from_studs
            bx = x1 + dx * (opening.from_studs + opening.width_studs)
            by = y1 + dy * (opening.from_studs + opening.width_studs)
            sa = self.screen(ax, ay)
            sb = self.screen(bx, by)
            c.create_line(*sa, *sb, fill=DOOR if opening.kind == "door" else WINDOW, width=6)
        for wall in self.storey.interior_walls:
            c.create_line(*self.screen(*wall.a), *self.screen(*wall.b), fill=INTERIOR, width=3)
        for ramp in self.storey.ramps:
            run = geo.ramp_run_studs(self.storey.wall_courses)
            dx, dy = DIRECTION_VECTORS[ramp.direction]
            tip = (ramp.at[0] + dx * run, ramp.at[1] + dy * run)
            c.create_line(*self.screen(*ramp.at), *self.screen(*tip), fill=RAMP, width=4, arrow=tk.LAST)

    def _draw_draft(self) -> None:
        c = self.canvas
        if self.draft:
            pts = []
            for x, y in self.draft:
                pts.extend(self.screen(x, y))
            if len(self.draft) >= 2:
                c.create_line(pts, fill=FOOTPRINT_DRAFT, width=2, dash=(4, 3))
            for x, y in self.draft:
                sx, sy = self.screen(x, y)
                c.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, outline=FOOTPRINT_DRAFT)
        if self.drag_start and self.drag_now:
            c.create_line(*self.screen(*self.drag_start), *self.screen(*self.drag_now),
                          fill=INTERIOR, width=3, dash=(3, 2))

    # --- files ------------------------------------------------------------
    def new_design(self) -> None:
        self.design = Design()
        self.path = None
        self.storey_index = 0
        self.draft = []
        self.height_var.set(self.storey.wall_courses)
        self.colour_var.set(self.design.colour)
        self.redraw()

    def open_design(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Lego house", "*.json")])
        if not path:
            return
        try:
            self.design = Design.load(path)
        except Exception as exc:  # noqa: BLE001 - surface any load failure to the user
            messagebox.showerror("Could not open", str(exc))
            return
        self.path = Path(path)
        self.storey_index = 0
        self.height_var.set(self.storey.wall_courses)
        self.colour_var.set(self.design.colour)
        self.roof_var.set(self.design.roof)
        self.redraw()

    def save_design(self) -> None:
        if self.path is None:
            self.save_design_as()
            return
        self.design.name = self.path.stem
        self.design.save(self.path)
        self.status.config(text=f"saved {self.path}")

    def save_design_as(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("Lego house", "*.json")])
        if not path:
            return
        self.path = Path(path)
        self.save_design()

    def show_problems(self) -> None:
        problems = self.design.validate()
        if not problems:
            messagebox.showinfo("Check design", "No problems. Ready to build.")
        else:
            messagebox.showwarning("Check design", "\n\n".join(problems))

    def preview(self) -> None:
        try:
            from .preview import show_preview
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("3D preview unavailable", str(exc))
            return
        show_preview(self.design)


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = argv if argv is not None else sys.argv[1:]
    design = None
    path = None
    if argv:
        path = Path(argv[0])
        if path.exists():
            design = Design.load(path)
    root = tk.Tk()
    root.geometry("1180x760")
    DesignerApp(root, design=design, path=path)
    root.mainloop()
    return 0
