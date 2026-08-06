from log_analyzer import metrics


def test_metrics_endpoint_lists_all_golden_signal_series():
    body, content_type = metrics.latest_metrics()
    text = body.decode()

    assert "text/plain" in content_type

    # traffic + errors
    assert "# TYPE http_requests_total counter" in text
    assert "# TYPE runs_total counter" in text
    # latency
    assert "# TYPE http_request_duration_seconds histogram" in text
    assert "# TYPE run_duration_seconds histogram" in text
    # saturation
    assert "# TYPE runs_in_progress gauge" in text
    assert "# TYPE runs_queue_depth gauge" in text


def test_unlabeled_gauges_default_to_zero():
    metrics.RUNS_IN_PROGRESS.set(0)
    metrics.RUNS_QUEUE_DEPTH.set(0)
    body, _ = metrics.latest_metrics()
    text = body.decode()
    assert "runs_in_progress 0.0" in text
    assert "runs_queue_depth 0.0" in text
