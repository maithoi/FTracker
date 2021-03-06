import os

import cv2

from app.frame_stream import frame_utils
from app.frame_stream.frame_stream import OutputFrameStream
from app.settings import DETECTION_COLOR, TRACK_COLOR


class OutSequences(OutputFrameStream):
    __detection_color = DETECTION_COLOR
    __tracking_color = TRACK_COLOR

    def __init__(self, seq_format, dir_path, *args, **kwargs):
        self.frames = []
        self.seq_format = seq_format
        self.dir_path = self.seq_format.split()
        self.init()

    def init(self):
        self.frames = []
        if not os.path.exists(self.dir_path):
            os.mkdir(self.dir_path)

    def is_done(self):
        return os.path.exists(self.dir_path)

    def release(self):
        self.frames = []

    def add(self, track_res):
        if track_res is None:
            return
        self.frames.append(track_res)

    def add_batch(self, frame_list):
        self.frames += frame_list

    def flush(self):
        for track_res in self.frames:
            new_track_res = frame_utils.mark_boxes(track_res)
            cv2.imwrite(self.seq_format.format(new_track_res.frame.fid), new_track_res.frame.frame_data)
        self.frames = []
