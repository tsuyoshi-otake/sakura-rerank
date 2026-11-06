"""Exact indexed surface/reading cover, weaker than converter reachability.

No POS connections, costs, search pruning or user intent are inferred. Literal
kana copying is a separately named diagnostic, never a pronunciation guess.
"""
from .tatoeba_input_units import kana_projection

MAX_STATES=129*257
MAX_EDGES=1_000_000


def _require(value,code):
    if not value:raise ValueError('lexical_cover_'+code)


class TargetSubstrings:
    """Linear-size suffix automaton; dictionary scan is linear in its text size."""
    def __init__(self,targets):
        _require(isinstance(targets,(list,tuple,set,frozenset)) and 1<=len(targets)<=1340
            and all(isinstance(t,str) and 1<=len(t)<=256 and '\0' not in t for t in targets),'target_population')
        values=sorted(set(targets))
        self.edges=[{}];length=[0];link=[-1];last=0
        for char in '\0'.join(values):
            current=len(self.edges);self.edges.append({});length.append(length[last]+1);link.append(0);p=last
            while p!=-1 and char not in self.edges[p]:self.edges[p][char]=current;p=link[p]
            if p==-1:link[current]=0
            else:
                q=self.edges[p][char]
                if length[p]+1==length[q]:link[current]=q
                else:
                    clone=len(self.edges);self.edges.append(dict(self.edges[q]));length.append(length[p]+1);link.append(link[q])
                    while p!=-1 and self.edges[p].get(char)==q:self.edges[p][char]=clone;p=link[p]
                    link[q]=link[current]=clone
            last=current

    def contains(self,value):
        if not isinstance(value,str) or not value or '\0' in value:return False
        node=0
        for char in value:
            node=self.edges[node].get(char)
            if node is None:return False
        return True


class Lexicon:
    """Trie over the already authenticated, relevant exact dictionary pairs."""
    def __init__(self,records):
        _require(isinstance(records,list) and len(records)<=500000,'record_bound')
        self.readings={};self.trie={}
        for record in records:
            _require(isinstance(record,dict) and 'surface' in record and 'readings' in record,'record_schema')
            surface=record['surface'];readings=record['readings']
            _require(isinstance(surface,str) and 1<=len(surface)<=256 and '\0' not in surface and surface not in self.readings,'surface')
            _require(isinstance(readings,list) and 1<=len(readings)<=64 and all(isinstance(r,str) and 1<=len(r)<=128 and '\0' not in r for r in readings)
                and readings==sorted(set(readings)),'readings')
            self.readings[surface]=tuple(readings);node=self.trie
            for char in surface:node=node.setdefault(char,{})
            node[None]=(surface,tuple(readings))

    def matches(self,target):
        result=[]
        for start in range(len(target)):
            found=[];node=self.trie
            for char in target[start:]:
                node=node.get(char)
                if node is None:break
                if None in node:found.append(node[None])
            result.append(found)
        return result

    def cover(self,target,reading,*,literal_kana=False,max_states=MAX_STATES,max_edges=MAX_EDGES):
        _require(isinstance(target,str) and 1<=len(target)<=256 and isinstance(reading,str) and 1<=len(reading)<=128
            and '\0' not in target+reading and type(literal_kana) is bool,'input')
        _require(type(max_states) is int and 1<=max_states<=MAX_STATES and type(max_edges) is int and 1<=max_edges<=MAX_EDGES,'work_limits')
        matches=self.matches(target);best=[{} for _ in range(len(target)+1)];best[0][0]=0;parents={};visited=1;examined=0
        for start in range(len(target)):
            for pos,depth in best[start].items():
                candidates=[(surface,value,'dictionary') for surface,values in matches[start] for value in values]
                if literal_kana:
                    value=kana_projection(target[start])
                    if value is not None:candidates.append((target[start],value,'literal_kana'))
                for surface,value,kind in candidates:
                    examined+=1
                    if examined>max_edges:return dict(status='work_bound',minimum_units=None,witness=None,visited_states=visited,examined_edges=examined)
                    if not reading.startswith(value,pos):continue
                    end,after=start+len(surface),pos+len(value)
                    old=best[end].get(after)
                    if old is None:
                        if visited>=max_states:return dict(status='work_bound',minimum_units=None,witness=None,visited_states=visited,examined_edges=examined)
                        visited+=1
                    if old is None or depth+1<old:
                        best[end][after]=depth+1
                        parents[(end,after)]=(start,pos,dict(target_start=start,target_end=end,reading_start=pos,reading_end=after,kind=kind))
        depth=best[-1].get(len(reading));witness=None
        if depth is not None:
            witness=[];key=(len(target),len(reading))
            while key!=(0,0):
                a,b,edge=parents[key];witness.append(edge);key=(a,b)
            witness.reverse()
        return dict(status='covered' if depth is not None else 'absent',minimum_units=depth,witness=witness,visited_states=visited,examined_edges=examined)
