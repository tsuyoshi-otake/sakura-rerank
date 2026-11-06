"""Fixed score decisions; no label access or threshold selection."""
import math

from sakura_rerank.evaluation_metrics import Observation


def fixed_observation(scores,status,count,threshold=None):
    if type(count) is not int or not 1<=count<=6:raise ValueError('source_score_candidate_count')
    if threshold is not None and (type(threshold) not in (int,float) or not math.isfinite(threshold) or threshold<0):
        raise ValueError('source_score_threshold')
    if status=='unavailable':return Observation('unavailable',None,False)
    if status=='error':return Observation('error',None,True)
    if status!='complete':raise ValueError('source_score_terminal_status')
    if len(scores)!=6 or any(not math.isfinite(float(value)) for value in scores):
        return Observation('malformed',None,True)
    order=tuple(sorted(range(count),key=lambda i:(-float(scores[i]),i)))
    # Python floats match the published float64 score-margin computation.
    if threshold is not None and (order[0]==0 or not float(scores[order[0]])-float(scores[0])>threshold):
        return Observation('abstained')
    return Observation('applied',order)
