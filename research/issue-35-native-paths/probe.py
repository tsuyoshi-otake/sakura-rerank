"""Capture pre-fusion native path edges in a pinned private source archive."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tarfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=HERE.parent/'issue-35-native-state'
spec=importlib.util.spec_from_file_location('native_path_build_support',BASE/'probe.py')
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
FILES=('probe.py','path_capture.rs.in','path_fixtures.rs.in')
SUPPORT=base.SUPPORT+('research/issue-35-native-state/probe.py','research/issue-35-native-state/dispatch_probe.rs.in',
                     'research/issue-35-native-state/long_conversion_probe.rs.in')
CORE='crates/sakura-core/src/conversion/'


def instrument(source):
    changed=base.instrument(source)
    assembly=source/CORE/'candidates/assembly.rs'
    raw=assembly.read_text(encoding='utf-8')
    raw=base.replace_once(raw,'pub struct ConversionCandidate {','pub struct ConversionCandidate {\n    pub research_path: ResearchPath,')
    raw=base.replace_once(raw,'        Some(candidate)\n','        candidate.research_path = candidate.research_path.rewritten_literal(surface,candidate.segments());\n        Some(candidate)\n')
    raw+='\n'+(HERE/'path_capture.rs.in').read_text(encoding='utf-8')
    files={CORE+'candidates/assembly.rs':raw,
           CORE+'candidates/mod.rs':base.replace_once((source/CORE/'candidates/mod.rs').read_text(),
                'pub use assembly::{ConversionCandidate, ConversionSegment};','pub use assembly::{ConversionCandidate, ConversionSegment, ResearchPath};')}
    path=source/CORE/'mod.rs'; raw=path.read_text(encoding='utf-8')
    raw=base.replace_once(raw,'pub use candidates::{ConversionCandidate, ConversionSegment};',
                         'pub use candidates::{ConversionCandidate, ConversionSegment, ResearchPath};')
    starts=[raw.index('fn '+name+'(') for name in ('make_lossless_fallback','make_synthetic_exact','make_candidate')]+[len(raw)]
    for index in (2,1,0):
        start,end=starts[index:index+2];part=raw[start:end]
        expr=('ResearchPath::synthetic(reading,text.as_str(),segments.as_slice(),"reading_fallback")' if index==0 else
              'ResearchPath::synthetic(lookup_reading,text.as_str(),segments.as_slice(),"generated_literal")' if index==1 else
              'ResearchPath::new("viterbi_materialization",reading,text.as_str(),research_edges)')
        part=base.replace_once(part,'    Ok(ConversionCandidate {','    Ok(ConversionCandidate {\n        research_path: '+expr+',')
        if index==2:
            part=base.replace_once(part,'    let mut text = FixedStr::new();','    let mut research_edges = Vec::new();\n    let mut text = FixedStr::new();')
            marker='        let reading_start =\n'
            capture='''        let research_category = match node.surface {
            Surface::Dictionary { .. } => "system_dictionary",
            Surface::User(_) => "user_dictionary",
            Surface::Reading => "reading_fallback",
            Surface::Katakana => "katakana_fallback",
            Surface::Passthrough => "passthrough_fallback",
            Surface::Literal(_) | Surface::Generated(_) => "generated_literal",
        };
        research_edges.push(ResearchPath::edge(node.start,node.end,text_start,text.len(),
            node.left_id,node.right_id,flags.bits(),research_category));
'''
            part=base.replace_once(part,marker,capture+marker)
        raw=raw[:start]+part+raw[end:]
    files[CORE+'mod.rs']=raw
    for name in ('dates','numerals','punctuation','single_kanji'):
        relative=CORE+'synthesis/'+name+'.rs';raw=(source/relative).read_text(encoding='utf-8')
        raw=base.replace_once(raw,'ConversionCandidate {','ConversionCandidate {\n                research_path: crate::conversion::ResearchPath::synthetic(reading,text.as_str(),segments.as_slice(),"generated_literal"),')
        files[relative]=raw
    dispatch=(source/'crates/sakura-engine/src/research_native_state.rs').read_text(encoding='utf-8')
    dispatch=base.replace_once(dispatch,'\\"fingerprint\\":{}}}',
                              '\\"fingerprint\\":{},\\"path\\":{},\\"display_segment_count\\":{}}}')
    dispatch=base.replace_once(dispatch,'native::fingerprint(candidate)))',
                              'native::fingerprint(candidate),candidate.research_path.json(),candidate.segments().len()))')
    dispatch=base.replace_once(dispatch,'{{\\"fixture\\":{index}', '{{\\"path_version\\":1,\\"fixture\\":{index}')
    dispatch=base.replace_once(dispatch,'"nonfinite", "not_ready", "missing"];',
        '"nonfinite", "not_ready", "missing", "fused", "mixed_user", "repair_dictionary", "numeric", "punctuation", "fallback"];')
    dispatch=base.replace_once(dispatch,'let conversion=conversion_fixture();','let conversion=path_fixture(scenario);')
    dispatch=base.replace_once(dispatch,'{"kanan"} else {"kana"}',
        '{"kanan"} else if *scenario=="fused" {"kanakanakana"} else if *scenario=="mixed_user" {"kana"}\n'
        '            else if *scenario=="numeric" {"123"} else if *scenario=="punctuation" {","}\n'
        '            else if *scenario=="fallback" {"xyz"} else {"kana"}')
    dispatch+='\n'+(HERE/'path_fixtures.rs.in').read_text(encoding='utf-8')
    files['crates/sakura-engine/src/research_native_state.rs']=dispatch
    for name,value in files.items():
        (source/name).write_bytes(value.encode())
        changed[name]=base.sha(source/name)
    return changed


def prepare(source,work):
    if (Path.home()/'tmp').resolve() not in work.parents or work.exists():raise ValueError('fresh private root required')
    if base.command('git','-C',str(source),'rev-parse','HEAD')!=base.HEAD or base.command('git','-C',str(source),'status','--porcelain'):
        raise ValueError('pinned clean source required')
    compiler=base.compiler();work.mkdir();packed=work/'source.tar'
    base.command('git','-C',str(source),'archive','--format=tar','--output='+str(packed),base.HEAD,
        '--','Cargo.toml','Cargo.lock','.cargo','crates','tools','data','corpus/session-replay/phase3-editing.snap')
    workspace=work/'source';workspace.mkdir()
    with tarfile.open(packed) as stream:
        members=stream.getmembers()
        if sum(m.size for m in members)>128*1024*1024 or any(not(m.isfile() or m.isdir()) for m in members):
            raise ValueError('source archive outside bound')
        stream.extractall(workspace,filter='data')
    original={p.relative_to(workspace).as_posix():base.sha(p) for p in workspace.rglob('*') if p.is_file()}
    changed=instrument(workspace)
    plan=dict(kind='native_state_probe_plan',version=3,path_contract='pre_fusion_converter_path_v1',
        source_head=base.HEAD,source_tree=base.command('git','-C',str(source),'rev-parse','HEAD^{tree}'),
        source_archive_sha256=base.sha(packed),original_source_files=original,instrumented_files=changed,
        implementation={name:base.sha(HERE/name) for name in FILES},
        support_implementation={name:base.sha(ROOT/name) for name in SUPPORT},compiler=compiler,
        lock_sha256=base.sha(workspace/'Cargo.lock'),test=base.TEST,build_jobs=1,expected_fixture_count=62,
        build_timeout_seconds=600,run_timeout_seconds=120,synthetic_response_injection=True,
        real_test=False,model_inference=False,gold_evidence=False,production_edits=False)
    base.save(work/'plan.json',plan)
    print(json.dumps(dict(status='prepared',source_files=len(original),plan_sha256=base.sha(work/'plan.json'))))


def run(work,expected):
    base.HERE=HERE;base.FILES=FILES;base.SUPPORT=SUPPORT
    return base.run(work,expected)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=('prepare','run'))
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--plan-sha256')
    args=parser.parse_args()
    if args.stage=='prepare':prepare(args.source_root.resolve(),args.work_root.resolve())
    else:sys.exit(run(args.work_root.resolve(),args.plan_sha256))
