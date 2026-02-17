import threading
import time

class LatestFrameGrabber:
    def __init__(self, cap, max_fps=None):
        self.cap = cap
        self.max_fps = max_fps
        self.lock = threading.Lock()
        self.frame = None
        self.ok = False
        self.stopped = False
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        last = 0.0
        while not self.stopped:
            if self.max_fps:
                now = time.time()
                if now - last < 1.0 / self.max_fps:
                    time.sleep(0.001)
                    continue
                last = now

            ok, frame = self.cap.read()
            with self.lock:
                self.ok = ok
                if ok:
                    self.frame = frame

    def read_latest(self):
        with self.lock:
            return self.ok, self.frame

    def stop(self):
        self.stopped = True
        if self.thread:
            self.thread.join(timeout=1.0)