import numpy as np

from app.buffer import Buffer, Batch
from app.frame_stream.frame_stream import InputFrameStream, OutputFrameStream
from app.frame_stream.frame_utils import TrackResult
from app.settings import logger, BATCH_SIZE, MATCHING, DETECTOR_MODEL_PATH
from detections.faceboxes.detector import Detector as Fb_detector
from app.face_tracker import FaceTracker
from matching.face_embedding.face_matching import main, Matcher
from copy import deepcopy
from itertools import islice
from detections.faceboxes.utils.timer import Timer
import time

DETECTION_BATCH = 16

class Processor(object):
    def __init__(self, ifs: InputFrameStream, ofs: OutputFrameStream):
        # self.face_detector = SFD_detector(model='detections/sfd/epoch_204.pth.tar')
        self.face_detector = Fb_detector(model_path=DETECTOR_MODEL_PATH)
        self.face_tracker = FaceTracker()
        # self.encoder = FaceEncoder()
        self.matcher = Matcher()
        self.ifs = ifs
        self.ofs = ofs

    def start(self):
        print('Start process')

        if self.ofs.is_done():
            print('Processed! skip')
            return

        buffer = Buffer()
        batch = Batch(BATCH_SIZE)
        flag = 0
        batch_tracks = []
        dt_time = Timer()
        m_time = Timer()
        tt_time = Timer()

        self.ofs.init()
        for (frame_id, frame) in self.ifs.get_iter():
            height, width, _ = frame.shape
            batch.update(frame, frame_id, height, width)
            dt_time.tic()
            detection = self.face_detector.infer(frame, path=False)  # xmin, ymin, xmax, ymax
            logger.debug('Frame {} have {} detections'.format(frame_id, len(detection)))
            detection = np.clip(detection, a_min=0, a_max=None)
            self.face_tracker.match_detection_tracking_hungarian(frame, detection)
            results = self.face_tracker.get_active_track()
            list_tracks = {}
            dt_time.toc()
            # print('dt time: {}'.format(dt_time.average_time))
            for box in results['geometries']:
                id = box['id']
                xmin = box['xmin']
                ymin = box['ymin']
                width = box['width']
                height = box['height']
                score = box['score']
                list_tracks[id] = (xmin, ymin, width, height, score)
            batch_tracks.append(list_tracks)
            if batch.count % BATCH_SIZE == 0:
                if MATCHING:
                    if batch.count % (BATCH_SIZE * 2) == 0:
                        flag = 0
                        print('Start matching')
                        batch_tracks = buffer.temp_batchtracks + batch_tracks

                        fids = list(buffer.temp_fids) + list(batch.fids)
                        bitmaps = list(buffer.temp_bitmaps) + list(batch.bitmaps)
                        m_time.tic()
                        main(self.matcher, batch_tracks, bitmaps, fids)
                        m_time.toc()
                        print('m time: {}'.format(m_time.average_time))
                        tt_time.tic()
                        for idx, tracks in zip(buffer.out_fids, buffer.out_batchtracks):
                            self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                        self.ofs.flush()
                        buffer.out_batchtracks += batch_tracks[BATCH_SIZE:]
                        buffer.out_fids += fids[BATCH_SIZE:]
                        buffer.out_bitmaps += bitmaps[BATCH_SIZE:]
                    else:
                        flag = 1
                        print('Save batch')
                        buffer.temp_batchtracks = deepcopy(batch_tracks)  # test this without deepcopy
                        buffer.temp_fids = deepcopy(list(batch.fids))
                        buffer.temp_bitmaps = deepcopy(list(batch.bitmaps))

                        print('Save out')
                        buffer.out_batchtracks += buffer.temp_batchtracks
                        buffer.out_fids += buffer.temp_fids
                        buffer.out_bitmaps += buffer.temp_bitmaps
                else:
                    for idx, tracks in zip(batch.fids, batch_tracks):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                    self.ofs.flush()
                batch_tracks = []

        # flush the queue -> process the remaining frames
        num_last = batch.count % BATCH_SIZE
        if num_last > 0:
            last_ids = list(islice(batch.fids, 0, BATCH_SIZE))[-num_last:]
            last_bitmaps = list(islice(batch.bitmaps, 0, BATCH_SIZE))[-num_last:]
            last_tracks = batch_tracks[-num_last:]
            if MATCHING:
                if flag == 0:
                    main(self.matcher, last_tracks, last_bitmaps, last_ids)
                    for idx, tracks in zip([buffer.out_fids[i] for i in range(BATCH_SIZE, BATCH_SIZE * 2)],
                                           [buffer.out_batchtracks[i] for i in range(BATCH_SIZE, BATCH_SIZE * 2)]):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))

                    for idx, tracks in zip(last_ids, last_tracks):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                    self.ofs.flush()
                else:
                    last_ids = list(buffer.temp_fids) + last_ids
                    last_bitmaps = list(buffer.temp_bitmaps) + last_bitmaps
                    last_tracks = buffer.temp_batchtracks + last_tracks
                    main(self.matcher, last_tracks, last_bitmaps, last_ids)

                    for idx, tracks in zip([buffer.out_fids[i] for i in range(0, BATCH_SIZE)],
                                           [buffer.out_batchtracks[i] for i in range(0, BATCH_SIZE)]):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))

                    for idx, tracks in zip(last_ids, last_tracks):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                    self.ofs.flush()
            else:
                for idx, tracks in zip(last_ids, last_tracks):
                    self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                self.ofs.flush()
        self.ofs.release()

    def start_batch(self):
        print('Start process')
        buffer = Buffer()
        batch = Batch(BATCH_SIZE)
        flag = 0
        batch_tracks = []
        dt_time = Timer()
        d_time = Timer()
        t_time = Timer()
        m_time = Timer()
        tt_time = Timer()
        self.ofs.init()
        frames = []
        for (frame_id, frame) in self.ifs.get_iter():
            frames.append(frame)
            height, width, _ = frame.shape
            batch.update(frame, frame_id, height, width)

            if batch.count % BATCH_SIZE == 0:
                d_time.tic()
                batch_results = self.face_detector.predict_images(batch.bitmaps)
                d_time.toc()
                print('db time ', d_time.average_time)
                for i, detection in enumerate(batch_results):
                    self.face_tracker.match_detection_tracking_hungarian(frames[i], detection)
                    results = self.face_tracker.get_active_track()
                    list_tracks = {}
                    for box in results['geometries']:
                        id = box['id']
                        xmin = box['xmin']
                        ymin = box['ymin']
                        width = box['width']
                        height = box['height']
                        score = box['score']
                        list_tracks[id] = (xmin, ymin, width, height, score)
                    batch_tracks.append(list_tracks)
                frames = []
            if batch.count % BATCH_SIZE == 0:
                if MATCHING:
                    if batch.count % (BATCH_SIZE * 2) == 0:
                        flag = 0

                        print('Start matching')
                        batch_tracks = buffer.temp_batchtracks + batch_tracks

                        fids = list(buffer.temp_fids) + list(batch.fids)
                        bitmaps = list(buffer.temp_bitmaps) + list(batch.bitmaps)
                        m_time.tic()
                        main(self.matcher, batch_tracks, bitmaps, fids)
                        m_time.toc()
                        print('m time: {}'.format(m_time.average_time))
                        tt_time.tic()
                        for idx, tracks in zip(buffer.out_fids, buffer.out_batchtracks):
                            self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                        self.ofs.flush()
                        tt_time.toc()
                        print('stream time: {}'.format(tt_time.average_time))
                        buffer.out_batchtracks += batch_tracks[BATCH_SIZE:]
                        buffer.out_fids += fids[BATCH_SIZE:]
                        buffer.out_bitmaps += bitmaps[BATCH_SIZE:]
                    else:
                        flag = 1
                        print('Save batch')
                        buffer.temp_batchtracks = deepcopy(batch_tracks)  # test this without deepcopy
                        buffer.temp_fids = deepcopy(list(batch.fids))
                        buffer.temp_bitmaps = deepcopy(list(batch.bitmaps))

                        print('Save out')
                        buffer.out_batchtracks += buffer.temp_batchtracks
                        buffer.out_fids += buffer.temp_fids
                        buffer.out_bitmaps += buffer.temp_bitmaps
                else:
                    for idx, tracks in zip(batch.fids, batch_tracks):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                    self.ofs.flush()
                batch_tracks = []

        # flush the queue -> process the remaining frames
        num_last = batch.count % BATCH_SIZE
        if num_last > 0:
            last_ids = list(islice(batch.fids, 0, BATCH_SIZE))[-num_last:]
            last_bitmaps = list(islice(batch.bitmaps, 0, BATCH_SIZE))[-num_last:]
            d_time.tic()
            batch_results = self.face_detector.predict_images(last_bitmaps)
            d_time.toc()
            print('db time ', d_time.average_time)
            for i, detection in enumerate(batch_results):
                self.face_tracker.match_detection_tracking_hungarian(last_bitmaps[i], detection)
                results = self.face_tracker.get_active_track()
                list_tracks = {}
                for box in results['geometries']:
                    id = box['id']
                    xmin = box['xmin']
                    ymin = box['ymin']
                    width = box['width']
                    height = box['height']
                    score = box['score']
                    list_tracks[id] = (xmin, ymin, width, height, score)
                batch_tracks.append(list_tracks)
            last_tracks = batch_tracks[-num_last:]
            if MATCHING:
                if flag == 0:
                    main(self.matcher, last_tracks, last_bitmaps, last_ids)
                    for idx, tracks in zip([buffer.out_fids[i] for i in range(BATCH_SIZE, BATCH_SIZE * 2)],
                                           [buffer.out_batchtracks[i] for i in range(BATCH_SIZE, BATCH_SIZE * 2)]):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))

                    for idx, tracks in zip(last_ids, last_tracks):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                    self.ofs.flush()
                else:
                    last_ids = list(buffer.temp_fids) + last_ids
                    last_bitmaps = list(buffer.temp_bitmaps) + last_bitmaps
                    last_tracks = buffer.temp_batchtracks + last_tracks
                    main(self.matcher, last_tracks, last_bitmaps, last_ids)

                    for idx, tracks in zip([buffer.out_fids[i] for i in range(0, BATCH_SIZE)],
                                           [buffer.out_batchtracks[i] for i in range(0, BATCH_SIZE)]):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))

                    for idx, tracks in zip(last_ids, last_tracks):
                        self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                    self.ofs.flush()
            else:
                for idx, tracks in zip(last_ids, last_tracks):
                    self.ofs.add(TrackResult(self.ifs.get(idx), tracks))
                self.ofs.flush()
        self.ofs.release()
