from game_bot.core.models import Point, Rect, Size


def rect_from_origin_size(origin: Point, size: Size) -> Rect:
    return Rect(origin.x, origin.y, origin.x + size.width, origin.y + size.height)


def offset_rect(rect: Rect, dx: int, dy: int) -> Rect:
    return Rect(rect.left + dx, rect.top + dy, rect.right + dx, rect.bottom + dy)


def clamp_rect_to_size(rect: Rect, size: Size) -> Rect:
    return Rect(
        max(0, min(rect.left, size.width)),
        max(0, min(rect.top, size.height)),
        max(0, min(rect.right, size.width)),
        max(0, min(rect.bottom, size.height)),
    )


def rect_center(rect: Rect) -> Point:
    return Point(rect.left + rect.width // 2, rect.top + rect.height // 2)
