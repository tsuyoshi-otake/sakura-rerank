"""Diagnostic adapter: execute captured native tensors, without re-encoding text."""
from sakura_rerank.current_tiny import validate_current
from sakura_rerank.evaluation_worker import cpu_session, cpu_scores


def reference_factory(artifacts, width):
    import numpy as np
    validate_current(artifacts, width)
    session = cpu_session(artifacts["weights"], width)
    class Scorer:
        def score(self, request):
            feed = {name: np.asarray(values, dtype=np.bool_ if name == "candidate_mask"
                    else np.float32 if name == "features" else np.int64)
                    for name, values in request["feed"].items()}
            return cpu_scores(session, feed)

        def close(self):
            pass
    return Scorer()
