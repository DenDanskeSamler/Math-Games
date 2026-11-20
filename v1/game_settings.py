import configparser
import math
from dataclasses import dataclass
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("config.ini")
CONFIG_OPTIONS = {
    "display": {
        "screen_width",
        "screen_height",
        "side_margin",
        "canvas_top",
        "ship_tray_top",
        "ship_tray_ship_offset",
        "ship_control_font_size",
        "ship_tray_font_size",
        "control_wrap_length",
        "laser_cannon_size",
    },
    "ships": {
        "cell_size",
        "lengths",
        "gap",
        "move_point_radius",
        "rotate_widget_radius",
        "initial_angle_radians",
        "max_angle_radians",
        "initial_height",
    },
    "laser": {
        "enabled",
        "show_toggle",
        "length",
        "pulse_duration",
        "pulse_trail_length",
        "hit_marker_duration",
    },
    "controls": {
        "angle_adjust_step",
        "height_adjust_step",
        "initial_repeat_delay_ms",
        "repeat_interval_ms",
    },
    "multiplayer": {
        "game_code_characters",
        "discovery_port",
        "discovery_timeout_seconds",
        "discovery_retry_seconds",
        "discovery_poll_interval_ms",
        "worker_retry_seconds",
        "worker_initial_wait_seconds",
        "worker_poll_interval_seconds",
    },
    "application": {"startup_delay_ms", "idle_sleep_seconds"},
}


@dataclass(frozen=True)
class GameSettings:
    screen_width: int
    screen_height: int
    side_margin: int
    canvas_top: int
    ship_tray_top: int
    ship_tray_ship_offset: int
    ship_cell_size: int
    ship_lengths: tuple[int, ...]
    ship_gap: int
    move_point_radius: int
    rotate_widget_radius: int
    ship_control_font_size: int
    ship_tray_font_size: int
    control_wrap_length: int
    laser_cannon_size: int
    initial_angle_radians: float
    max_angle_radians: float
    initial_height: float
    laser_enabled: bool
    show_laser_toggle: bool
    laser_length: int
    laser_pulse_duration: float
    laser_pulse_trail_length: int
    hit_marker_duration: float
    angle_adjust_step: float
    height_adjust_step: float
    initial_repeat_delay_ms: int
    repeat_interval_ms: int
    game_code_characters: str
    discovery_port: int
    discovery_timeout_seconds: float
    discovery_retry_seconds: float
    discovery_poll_interval_ms: int
    worker_retry_seconds: float
    worker_initial_wait_seconds: float
    worker_poll_interval_seconds: float
    startup_delay_ms: int
    idle_sleep_seconds: float


def load_settings(path: Path = CONFIG_PATH) -> GameSettings:
    parser = configparser.ConfigParser()
    try:
        with path.open(encoding="utf-8") as config_file:
            parser.read_file(config_file)
    except OSError as error:
        raise RuntimeError(f"Could not read MathShips config at {path}: {error}") from error

    _validate_options(parser, path)
    settings = GameSettings(
        screen_width=parser.getint("display", "screen_width"),
        screen_height=parser.getint("display", "screen_height"),
        side_margin=parser.getint("display", "side_margin"),
        canvas_top=parser.getint("display", "canvas_top"),
        ship_tray_top=parser.getint("display", "ship_tray_top"),
        ship_tray_ship_offset=parser.getint("display", "ship_tray_ship_offset"),
        ship_cell_size=parser.getint("ships", "cell_size"),
        ship_lengths=tuple(
            int(length.strip())
            for length in parser.get("ships", "lengths").split(",")
        ),
        ship_gap=parser.getint("ships", "gap"),
        move_point_radius=parser.getint("ships", "move_point_radius"),
        rotate_widget_radius=parser.getint("ships", "rotate_widget_radius"),
        ship_control_font_size=parser.getint("display", "ship_control_font_size"),
        ship_tray_font_size=parser.getint("display", "ship_tray_font_size"),
        control_wrap_length=parser.getint("display", "control_wrap_length"),
        laser_cannon_size=parser.getint("display", "laser_cannon_size"),
        initial_angle_radians=parser.getfloat("ships", "initial_angle_radians"),
        max_angle_radians=parser.getfloat("ships", "max_angle_radians"),
        initial_height=parser.getfloat("ships", "initial_height"),
        laser_enabled=parser.getboolean("laser", "enabled"),
        show_laser_toggle=parser.getboolean("laser", "show_toggle"),
        laser_length=parser.getint("laser", "length"),
        laser_pulse_duration=parser.getfloat("laser", "pulse_duration"),
        laser_pulse_trail_length=parser.getint("laser", "pulse_trail_length"),
        hit_marker_duration=parser.getfloat("laser", "hit_marker_duration"),
        angle_adjust_step=parser.getfloat("controls", "angle_adjust_step"),
        height_adjust_step=parser.getfloat("controls", "height_adjust_step"),
        initial_repeat_delay_ms=parser.getint("controls", "initial_repeat_delay_ms"),
        repeat_interval_ms=parser.getint("controls", "repeat_interval_ms"),
        game_code_characters=parser.get("multiplayer", "game_code_characters"),
        discovery_port=parser.getint("multiplayer", "discovery_port"),
        discovery_timeout_seconds=parser.getfloat(
            "multiplayer", "discovery_timeout_seconds"
        ),
        discovery_retry_seconds=parser.getfloat(
            "multiplayer", "discovery_retry_seconds"
        ),
        discovery_poll_interval_ms=parser.getint(
            "multiplayer", "discovery_poll_interval_ms"
        ),
        worker_retry_seconds=parser.getfloat(
            "multiplayer", "worker_retry_seconds"
        ),
        worker_initial_wait_seconds=parser.getfloat(
            "multiplayer", "worker_initial_wait_seconds"
        ),
        worker_poll_interval_seconds=parser.getfloat(
            "multiplayer", "worker_poll_interval_seconds"
        ),
        startup_delay_ms=parser.getint("application", "startup_delay_ms"),
        idle_sleep_seconds=parser.getfloat("application", "idle_sleep_seconds"),
    )
    _validate(settings, path)
    return settings


def _validate_options(parser: configparser.ConfigParser, path: Path) -> None:
    unexpected_sections = set(parser.sections()) - CONFIG_OPTIONS.keys()
    unexpected_options = {
        f"{section}.{option}"
        for section in parser.sections()
        for option in parser.options(section)
        if section not in CONFIG_OPTIONS or option not in CONFIG_OPTIONS[section]
    }
    if parser.defaults():
        unexpected_options.update(
            f"DEFAULT.{option}" for option in parser.defaults()
        )
    if unexpected_sections or unexpected_options:
        details = sorted(unexpected_sections | unexpected_options)
        raise ValueError(
            f"Unknown MathShips config entries in {path}: {', '.join(details)}"
        )


def _validate(settings: GameSettings, path: Path) -> None:
    positive_values = {
        "display.screen_width": settings.screen_width,
        "display.screen_height": settings.screen_height,
        "display.ship_control_font_size": settings.ship_control_font_size,
        "display.ship_tray_font_size": settings.ship_tray_font_size,
        "display.control_wrap_length": settings.control_wrap_length,
        "display.laser_cannon_size": settings.laser_cannon_size,
        "ships.cell_size": settings.ship_cell_size,
        "ships.move_point_radius": settings.move_point_radius,
        "ships.rotate_widget_radius": settings.rotate_widget_radius,
        "laser.length": settings.laser_length,
        "laser.pulse_duration": settings.laser_pulse_duration,
        "laser.hit_marker_duration": settings.hit_marker_duration,
        "controls.angle_adjust_step": settings.angle_adjust_step,
        "controls.height_adjust_step": settings.height_adjust_step,
        "controls.initial_repeat_delay_ms": settings.initial_repeat_delay_ms,
        "controls.repeat_interval_ms": settings.repeat_interval_ms,
        "multiplayer.discovery_timeout_seconds": settings.discovery_timeout_seconds,
        "multiplayer.discovery_retry_seconds": settings.discovery_retry_seconds,
        "multiplayer.discovery_poll_interval_ms": settings.discovery_poll_interval_ms,
        "multiplayer.worker_retry_seconds": settings.worker_retry_seconds,
        "multiplayer.worker_initial_wait_seconds": settings.worker_initial_wait_seconds,
        "multiplayer.worker_poll_interval_seconds": settings.worker_poll_interval_seconds,
        "application.startup_delay_ms": settings.startup_delay_ms,
        "application.idle_sleep_seconds": settings.idle_sleep_seconds,
    }
    float_values = (
        settings.initial_angle_radians,
        settings.max_angle_radians,
        settings.initial_height,
        settings.laser_pulse_duration,
        settings.hit_marker_duration,
        settings.angle_adjust_step,
        settings.height_adjust_step,
        settings.discovery_timeout_seconds,
        settings.discovery_retry_seconds,
        settings.worker_retry_seconds,
        settings.worker_initial_wait_seconds,
        settings.worker_poll_interval_seconds,
        settings.idle_sleep_seconds,
    )
    if not all(math.isfinite(value) for value in float_values):
        raise ValueError(
            f"Invalid MathShips config at {path}: floating-point values must be finite."
        )

    invalid_values = [
        name
        for name, value in positive_values.items()
        if not math.isfinite(value) or value <= 0
    ]
    if invalid_values:
        raise ValueError(
            f"Invalid MathShips config at {path}: values must be positive: "
            + ", ".join(invalid_values)
        )

    if (
        settings.side_margin < 0
        or settings.canvas_top < 0
        or settings.ship_tray_top < 0
        or settings.ship_tray_ship_offset < 0
        or settings.ship_gap < 0
        or settings.laser_pulse_trail_length < 0
        or not settings.ship_lengths
        or any(length <= 0 for length in settings.ship_lengths)
    ):
        raise ValueError(
            f"Invalid MathShips config at {path}: dimensions cannot be negative or empty."
        )
    if (
        settings.screen_width <= 2 * settings.side_margin
        or settings.screen_height <= settings.canvas_top + settings.side_margin
        or settings.ship_tray_top >= settings.canvas_top
    ):
        raise ValueError(
            f"Invalid MathShips config at {path}: board dimensions do not fit the screen."
        )
    ship_row_width = (
        len(settings.ship_lengths) * settings.ship_cell_size
        + (len(settings.ship_lengths) - 1) * settings.ship_gap
    )
    board_width = settings.screen_width - 2 * settings.side_margin
    ship_area_height = (
        settings.screen_height - settings.ship_tray_top - settings.side_margin
    )
    if (
        ship_row_width > board_width
        or max(settings.ship_lengths) * settings.ship_cell_size > ship_area_height
    ):
        raise ValueError(
            f"Invalid MathShips config at {path}: ships do not fit in the configured play area."
        )
    if settings.max_angle_radians <= 0:
        raise ValueError(
            f"Invalid MathShips config at {path}: max_angle_radians must be positive."
        )
    if not (
        -settings.max_angle_radians
        <= settings.initial_angle_radians
        <= settings.max_angle_radians
    ):
        raise ValueError(
            f"Invalid MathShips config at {path}: initial angle is outside the configured limit."
        )
    if not (
        0
        <= settings.initial_height
        <= settings.screen_height - settings.canvas_top - settings.side_margin
    ):
        raise ValueError(
            f"Invalid MathShips config at {path}: initial height is outside the board."
        )
    if not 1 <= settings.discovery_port <= 65535:
        raise ValueError(
            f"Invalid MathShips config at {path}: discovery_port must be between 1 and 65535."
        )
    if (
        not settings.game_code_characters
        or len(set(settings.game_code_characters)) != len(settings.game_code_characters)
    ):
        raise ValueError(
            f"Invalid MathShips config at {path}: game code characters must be unique and non-empty."
        )


SETTINGS = load_settings()
