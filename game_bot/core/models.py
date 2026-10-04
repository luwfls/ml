from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Size:
    width: int
    height: int


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    window_rect: Rect
    client_size: Size
    client_origin_screen: Point
    client_rect_screen: Rect


@dataclass(frozen=True)
class CaptureResult:
    path: Path
    hwnd: int
    title: str
    rect: Rect
    size: Size


@dataclass(frozen=True)
class TemplateImage:
    path: Path
    width: int
    height: int


@dataclass(frozen=True)
class MatchResult:
    found: bool
    score: float
    box: Rect
    center: Point
    template_path: Path
    image_path: Path
    debug_path: Path | None = None
    scale: float = 1.0
    brightness_ratio: float = 1.0


@dataclass(frozen=True)
class InputResult:
    success: bool
    hwnd: int
    client_point: Point | None
    screen_point: Point | None
    message: str
    backend: str


@dataclass(frozen=True)
class ActionResult:
    success: bool
    action: str
    hwnd: int
    message: str
    client_point: Point | None = None
    screen_point: Point | None = None
    before_screenshot: Path | None = None
    after_screenshot: Path | None = None
    elapsed_ms: int | None = None


@dataclass(frozen=True)
class TargetSpec:
    name: str
    type: str
    template_path: Path
    threshold: float
    region_name: str | None = None
    scales: tuple[float, ...] | None = None


@dataclass(frozen=True)
class StateRule:
    type: str
    target: str | None = None


@dataclass(frozen=True)
class StateDetectionResult:
    state: str
    known: bool
    image_path: Path
    message: str
    matched_rule: StateRule | None = None
    matched_target: str | None = None
    match_result: MatchResult | None = None
    debug_paths: tuple[Path, ...] = ()
