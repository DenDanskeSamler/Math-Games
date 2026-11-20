import math
import time

import pygame as pg

from game_settings import SETTINGS


class LaserEffects:
    def __init__(self, length, origin_x, canvas_bottom):
        self.length = length
        self.origin_x = origin_x
        self.canvas_bottom = canvas_bottom
        self.overlay = None
        self.pulse = None
        self.burns = []

    def set_overlay(self, overlay):
        self.overlay = overlay

    def start_pulse(self, angle, height):
        started_at = time.monotonic()
        self.pulse = {
            "started_at": started_at,
            "angle": angle,
            "height": height,
        }
        self.burns.append({
            "started_at": started_at,
            "angle": angle,
            "height": height,
        })

    def draw_beam(self, x, y, angle, enabled, color):
        if enabled:
            end_x = x + self.length * math.cos(angle)
            end_y = y + self.length * math.sin(angle)
            pg.draw.line(self.overlay, color, (x, y), (end_x, end_y), 3)

    def draw_burns(self, now):
        for burn in self.burns:
            elapsed = max(0, now - burn["started_at"])
            progress = min(elapsed / SETTINGS.laser_pulse_duration, 1)
            distance = self.length * progress
            angle = burn["angle"]
            x = self.origin_x
            y = self._laser_y(burn["height"])
            endpoint = (
                round(x + distance * math.cos(angle)),
                round(y + distance * math.sin(angle)),
            )
            pg.draw.line(
                self.overlay,
                (125, 125, 125, 155),
                (x, y),
                endpoint,
                4,
            )

    def draw_pulse(self, now):
        if self.pulse is None:
            return
        elapsed = now - self.pulse["started_at"]
        if elapsed < 0 or elapsed >= SETTINGS.laser_pulse_duration:
            return

        distance = self.length * elapsed / SETTINGS.laser_pulse_duration
        tail_distance = max(
            0, distance - SETTINGS.laser_pulse_trail_length
        )
        angle = self.pulse["angle"]
        x = self.origin_x
        y = self._laser_y(self.pulse["height"])
        tail = (
            round(x + tail_distance * math.cos(angle)),
            round(y + tail_distance * math.sin(angle)),
        )
        head = (
            round(x + distance * math.cos(angle)),
            round(y + distance * math.sin(angle)),
        )
        pg.draw.line(self.overlay, (0, 130, 255, 110), tail, head, 13)
        pg.draw.line(self.overlay, (0, 220, 255, 235), tail, head, 5)
        pg.draw.circle(self.overlay, (255, 255, 255, 255), head, 5)

    def _laser_y(self, height):
        return self.canvas_bottom - height
