"""Select a road for crew-driven demolition and material export."""

from typing import Any

from city import CityMap
from models import Road
from ..base import CanvasTool


TOOL_ID = "deconstruct_road"
OVERLAY_TAG = "deconstruct_road_tool_overlay"


def road_at(city: CityMap, position: tuple[float, float], tolerance: float) -> Road | None:
    for road in reversed(city.roads):
        if road.distance_to(position) <= road.width / 2 + tolerance:
            return road
    return None


class DeconstructRoadTool(CanvasTool):
    name = "Deconstruct road"
    cursor = "crosshair"

    def __init__(self, host: Any) -> None:
        super().__init__(host)
        self.message = "Click a road to send a crew and export its salvage."
        self._dirty = True

    def activate(self) -> None:
        self.host.canvas.configure(cursor=self.cursor)
        self._dirty = True
        self.refresh()

    def deactivate(self) -> None:
        self.host.canvas.configure(cursor="")
        self.host.canvas.delete(OVERLAY_TAG)

    def on_canvas_click(self, event: Any) -> None:
        road = road_at(
            self.host.city_map, self.host.screen_to_world((event.x, event.y)),
            4 / max(self.host.camera_zoom, 0.01),
        )
        if road is None:
            self.message = "No road there. Click a road surface."
        else:
            try:
                self.host.construction_simulation.request_road_deconstruction(self.host.city_map, road)
            except ValueError as error:
                self.message = str(error)
            else:
                self.message = f"Deconstruction scheduled: {road.name}."
                self.host.redraw_world()
        self._dirty = True
        self.refresh()

    def refresh(self) -> None:
        if self._dirty:
            self.host.canvas.delete(OVERLAY_TAG)
            self.host.canvas.create_text(
                12, 12, anchor="nw", text=self.message, fill="#ffffff",
                font=("Arial", 11, "bold"), tags=OVERLAY_TAG,
            )
            self._dirty = False
        self.host.canvas.tag_raise(OVERLAY_TAG)

    def reset(self) -> None:
        self.message = "Click a road to send a crew and export its salvage."
        self._dirty = True


TOOL_CLASS = DeconstructRoadTool
