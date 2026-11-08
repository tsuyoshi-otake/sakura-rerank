"""Separate evaluation tensor formulas, including missing and truncated candidates."""
from sakura_rerank.data.consumed_numeric import SHAPES, dtype_for


def original_arrays(targets, snapshots):
    import numpy as np
    arrays={name:np.zeros((len(targets),*shape),dtype=dtype_for(name)) for name,shape in SHAPES.items()}
    arrays['gold'].fill(-1)
    def chars(text,width):
        chosen=text[:width]
        return [1+(ord(c)*2654435761)%13311 for c in chosen]+[0]*(width-len(chosen)),len(chosen)
    for i,row in enumerate(targets):
        if not 8<=len(row['left_context'])<=64 or not 2<=len(row['reading'])<=32:
            raise ValueError('evaluation_input_length')
        for prefix,field,width in (('context','left_context',64),('reading','reading',32)):
            arrays[prefix+'_ids'][i],arrays[prefix+'_lengths'][i]=chars(row[field],width)
        snapshot=snapshots.get(row['candidate_request_id'])
        if snapshot is None:
            continue
        top=snapshot['candidate_snapshots']['training_top32']['candidates'][:6]
        if top!=snapshot['candidate_snapshots']['production_top6']['candidates']:
            raise ValueError('evaluation_candidate_prefix')
        costs=[float(c['local_cost']) for c in top]
        if not costs:
            continue
        minimum,span=min(costs),max(max(costs)-min(costs),1.)
        for j,candidate in enumerate(top):
            surface=candidate['surface'];prefix=0
            for a,b in zip(row['reading'],surface):
                if a!=b:break
                prefix+=1
            arrays['candidate_ids'][i,j],arrays['candidate_lengths'][i,j]=chars(surface,32)
            arrays['candidate_mask'][i,j]=True
            arrays['features'][i,j]=[-(costs[j]-minimum)/span,-j/5,
                min(len(candidate['segments']),8)/8,len(surface)/32,
                prefix/max(len(row['reading']),len(surface),1),
                float(candidate['source_category']=='system_dictionary'),
                -np.float32(np.log1p(max(costs[j]-minimum,0.)/1000.))]
            arrays['correct_mask'][i,j]=surface==row['target']
            arrays['baseline_equivalent'][i,j]=surface==top[0]['surface']
            if surface==row['target'] and arrays['gold'][i]<0:
                arrays['gold'][i]=j
    return arrays


def verify_saved(targets,snapshots,saved):
    import numpy as np
    expected=original_arrays(targets,snapshots)
    if set(saved)!=set(expected):
        raise ValueError('evaluation_array_names')
    for name,value in expected.items():
        if (saved[name].shape!=value.shape or saved[name].dtype!=value.dtype
                or not np.array_equal(saved[name],value) or saved[name].tobytes()!=value.tobytes()):
            raise ValueError('evaluation_complete_tensor_difference')
    return dict(rows=len(targets),arrays=len(expected),elements=sum(a.size for a in expected.values()),bitwise_equal=True)
