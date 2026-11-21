from clipyyy.reframe import Face, center_plan, detection_dimensions, dominant, face_box, smooth


def test_center_plan_for_landscape_source():
    plan = center_plan(1920, 1080, 9 / 16, None)
    box = plan["crop_boxes"][0]
    assert box["height"] == 1080 and box["width"] == 608
    assert box["x"] == (1920 - 608) // 2


def test_center_plan_square():
    box = center_plan(1920, 1080, 1.0, None)["crop_boxes"][0]
    assert box["width"] == box["height"] == 1080


def test_face_box_stays_inside_frame():
    face = Face(0.9, 0.1, 0.08, 0.15)
    box = face_box(face, 1920, 1080, 1900, 150, 9 / 16)
    assert box["x"] >= 0 and box["x"] + box["width"] <= 1920
    assert box["y"] >= 0 and box["y"] + box["height"] <= 1080


def test_dominant_prefers_largest_face():
    small, big = Face(0.1, 0.1, 0.05, 0.05), Face(0.6, 0.3, 0.2, 0.2)
    assert dominant([small, big]) is big
    assert dominant([]) is None


def test_smooth_averages_neighbours():
    assert smooth([(0, 0), (3, 3), (0, 0)])[1] == (1, 1)


def test_detection_dimensions_downscale_landscape_and_keep_aspect():
    assert detection_dimensions(1920, 1080) == (640, 360)


def test_detection_dimensions_do_not_upscale_small_video():
    assert detection_dimensions(640, 360) == (640, 360)



def test_track_primary_faces_prefers_continuity_over_a_larger_background_face():
    from clipyyy.reframe import track_primary_faces

    primary_first = Face(0.10, 0.20, 0.18, 0.18)
    background_first = Face(0.65, 0.20, 0.14, 0.14)
    primary_next = Face(0.13, 0.20, 0.18, 0.18)
    background_next = Face(0.60, 0.20, 0.28, 0.28)

    tracked = track_primary_faces([[primary_first, background_first], [primary_next, background_next]])

    assert tracked == [primary_first, primary_next]


def test_track_primary_faces_reacquires_largest_face_after_long_disappearance():
    from clipyyy.reframe import track_primary_faces

    first = Face(0.10, 0.20, 0.20, 0.20)
    new_primary = Face(0.65, 0.20, 0.30, 0.30)
    smaller = Face(0.15, 0.20, 0.12, 0.12)

    tracked = track_primary_faces([[first], [], [], [], [new_primary, smaller]])

    assert tracked == [first, None, None, None, new_primary]


def test_track_primary_faces_keeps_missing_frames_for_fallback_ratio():
    from clipyyy.reframe import track_primary_faces

    face = Face(0.2, 0.2, 0.2, 0.2)

    assert track_primary_faces([[face], [], [face]]) == [face, None, face]


def test_prepare_clips_skips_full_video_intermediate_without_broll(monkeypatch, tmp_path):
    import clipyyy.reframe as reframe

    monkeypatch.setattr(reframe, "probe", lambda path: (1920, 1080, 3600.0))
    monkeypatch.setattr(
        reframe,
        "plan_crop",
        lambda path, aspect, start, end: {
            "crop_mode": "face",
            "crop_boxes": [{"t": 0.0, "x": 500, "y": 100, "width": 300, "height": 500}],
        },
    )
    monkeypatch.setattr(
        reframe,
        "run_ffmpeg",
        lambda args: (_ for _ in ()).throw(AssertionError("unexpected full-resolution encode")),
    )

    result = reframe.prepare_clips(
        {"video_path": str(tmp_path / "source.mp4")},
        {
            "clips": [
                {"rank": 1, "start_seconds": 30.0, "end_seconds": 60.0},
            ]
        },
        tmp_path / "work",
        9 / 16,
        True,
        False,
    )

    assert len(result["clips"]) == 1
    assert "speaker_path" not in result["clips"][0]
    assert result["clips"][0]["crop_mode"] == "face"
