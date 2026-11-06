"""Changed-input source-presence pairs, with every original parent retained."""
from collections import Counter

from sakura_rerank.data.source_reading_units import VIEWS
from extent_common import PRIOR,measure,summary,read,require
from prepare_extents import flatten


def measurements(source,snapshots,states):
    views=flatten(source)
    # The old numeric census accepts the same seven-field research input.
    # This explicit projection confers none of the old preparation permissions.
    projected=[dict(status=v['status'],input=v['input'],lineage_sha256=v['lineage_sha256'],
        lineage=dict(parent_original_row_sha256=parent,rebuilt_input_sha256=v['lineage']['candidate_input_sha256']))
        for parent,_,v in views]
    result=measure(projected,snapshots,states)
    for record,(parent,name,view) in zip(result,views,strict=True):
        require(record['parent_original_row_sha256']==parent,'measurement_parent')
        record.update(view=name,expanded=view['expanded'],within_preparation_bounds=view['within_preparation_bounds'])
    return result


def pairs(rows,selected,view,k):
    table={(r['parent_original_row_sha256'],r['view']):r for r in rows}
    counts=Counter({key:0 for key in ('both_present','original_only','extent_only','neither_present','original_unmeasured','extent_unmeasured','both_unmeasured')})
    expanded=0
    for parent in selected:
        original,extent=table[(parent,'original_ruby')],table[(parent,view)];expanded+=extent['expanded']
        a,b=original['status']=='complete',extent['status']=='complete'
        if not a or not b:key='both_unmeasured' if not a and not b else 'original_unmeasured' if not a else 'extent_unmeasured'
        else:
            x,y=original['candidate']['presence'][str(k)],extent['candidate']['presence'][str(k)]
            key='both_present' if x and y else 'original_only' if x else 'extent_only' if y else 'neither_present'
            if not extent['expanded']:require(x==y,'unchanged_extent_candidate_parity')
        counts[key]+=1
    require(sum(counts.values())==len(selected),'paired_denominator')
    return dict(parents=len(selected),expanded_rows=expanded,counts=dict(counts))


def aggregate(rows):
    old=read(PRIOR/'measurements.json')['rows'];all_parents={r['parent_original_row_sha256'] for r in old}
    missing={r['parent_original_row_sha256'] for r in old if r['status']=='complete' and not r['candidate']['presence']['32']}
    table={(r['parent_original_row_sha256'],r['view']):r for r in rows}
    require(len(all_parents)==335 and len(missing)==305 and len(table)==len(rows)==1005,'comparison_population')
    for previous in old:
        current=table[(previous['parent_original_row_sha256'],'original_ruby')]
        if previous['status']=='complete':
            require(current['status']=='complete' and current['candidate']==previous['candidate']
                and current['numeric']==previous['numeric'] and current['encoding_profile']==previous['encoding_profile'],'original318_replay')
    census={}
    for name in VIEWS:
        group=[r for r in rows if r['view']==name];value=summary(group)
        value['expanded_rows']=sum(r['expanded'] for r in group)
        value['candidate_and_preparation_bounds_rows']=sum(r['status']=='complete' and r['candidate']['eligible'] and r['within_preparation_bounds'] for r in group)
        census[name]=value
    comparisons={group:{view:{str(k):pairs(rows,selected,view,k) for k in (1,5,6,10,32)} for view in VIEWS[1:]}
        for group,selected in (('all335',all_parents),('old305_top32_missing',missing))}
    return dict(parents=335,view_slots=1005,original318_reproduced=True,original17_new_diagnostic_only=True,
        views=census,paired_source_presence=comparisons,training_admission=False,gold_admission=False)
