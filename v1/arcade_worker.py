import queue

from arcade_api import ApiRequestError, api_request
from game_settings import SETTINGS


class ArcadeWorker:
    def __init__(
        self,
        server_url,
        token,
        game_id,
        actions,
        events,
        stop_event,
        state_loaded,
        state_lock,
        local_state,
    ):
        self.server_url = server_url
        self.token = token
        self.game_id = game_id
        self.actions = actions
        self.events = events
        self.stop_event = stop_event
        self.state_loaded = state_loaded
        self.state_lock = state_lock
        self.local_state = local_state

    def request(self, path, method="GET", body=None):
        if not self.server_url or not self.token:
            raise RuntimeError("You are not connected to the Arcade server.")
        return api_request(
            self.server_url,
            path,
            method=method,
            token=self.token,
            body=body,
        )

    def run(self):
        game_path = f"/api/multiplayer/games/{self.game_id}"
        game_finished = False
        while not self.stop_event.is_set():
            try:
                response = self.request(game_path)
            except ApiRequestError as error:
                self.events.put(("error", str(error)))
                if self.stop_event.wait(SETTINGS.worker_retry_seconds):
                    return
                continue
            game_finished = response["status"] == "finished"
            self.events.put(("state", response))
            if self.state_loaded.wait(SETTINGS.worker_initial_wait_seconds):
                break
            if self.stop_event.is_set():
                return

        while not self.stop_event.is_set():
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                action = None

            if action:
                try:
                    action_path = (
                        f"{game_path}/lock"
                        if action == "lock"
                        else f"{game_path}/fire"
                    )
                    response = self.request(
                        action_path,
                        method="POST",
                    )
                except ApiRequestError as error:
                    self.events.put(("error", str(error), action))
                    if self.stop_event.wait(SETTINGS.worker_retry_seconds):
                        return
                    continue
                game_finished = response["status"] == "finished"
                self.events.put(("state", response))

            try:
                if game_finished:
                    response = self.request(game_path)
                else:
                    with self.state_lock:
                        snapshot = dict(self.local_state)
                    response = self.request(
                        f"{game_path}/state",
                        method="PUT",
                        body=snapshot,
                    )
            except ApiRequestError as error:
                if error.status_code == 409:
                    game_finished = True
                    continue
                self.events.put(("error", str(error)))
                if self.stop_event.wait(SETTINGS.worker_retry_seconds):
                    return
                continue
            game_finished = response["status"] == "finished"
            self.events.put(("state", response))
            if self.stop_event.wait(SETTINGS.worker_poll_interval_seconds):
                return
