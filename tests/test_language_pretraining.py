import unittest

from sakura_rerank.data.language_windows import fragment_windows
from sakura_rerank.language_pretraining import encoder_parameters,next_character_logits
from sakura_rerank.research_tiny import build_model,character_ids


class LanguageWindowTests(unittest.TestCase):
    def test_windows_are_causal_bounded_and_replay_identically(self):
        text="合成試験用の日本語文脈です。"*6
        windows=fragment_windows(text)
        self.assertEqual(windows,fragment_windows(text))
        self.assertEqual(len(windows),6)
        for row in windows:
            p=row["position"]
            self.assertEqual(row["context"],text[max(0,p-64):p])
            self.assertEqual(row["next_character"],text[p])
            self.assertTrue(8<=len(row["context"])<=64)

    def test_short_fragment_and_position_bounds_are_rejected(self):
        for text,positions in (("12345678",6),("x"*129,6),("x"*10,7)):
            with self.assertRaises(ValueError):fragment_windows(text,positions)

    def test_window_identity_depends_on_literal_context_and_next_character(self):
        first=fragment_windows("12345678甲")[0];second=fragment_windows("12345678乙")[0]
        self.assertEqual(first["context"],second["context"])
        self.assertNotEqual(first["window_id"],second["window_id"])


class TiedLanguageHeadTests(unittest.TestCase):
    def setUp(self):
        import torch
        torch.set_num_threads(1)
        self.torch=torch;torch.manual_seed(1)
        self.model=build_model();self.model.train()
        ids,length=character_ids("合成試験用日本語文脈",64)
        self.ids=torch.tensor([ids]);self.lengths=torch.tensor([length])

    def test_only_encoder_and_embedding_change_and_no_parameters_are_added(self):
        t=self.torch;model=self.model
        before={k:v.clone() for k,v in model.state_dict().items()}
        parameters=encoder_parameters(model);optimizer=t.optim.AdamW(parameters,lr=.001)
        logits=next_character_logits(model,self.ids,self.lengths)
        self.assertEqual(logits.shape,(1,13312));self.assertEqual(float(logits[0,0].detach()),-10000)
        target=t.tensor([character_ids("甲",1)[0][0]])
        loss=t.nn.functional.cross_entropy(logits,target);loss.backward();optimizer.step()
        self.assertEqual(set(before),set(model.state_dict()))
        self.assertTrue(all(t.equal(v,before[k]) for k,v in model.state_dict().items() if k.startswith("scorer.")))
        self.assertFalse(t.equal(model.embedding.weight,before["embedding.weight"]))
        self.assertFalse(t.equal(model.encoder.weight_ih_l0,before["encoder.weight_ih_l0"]))

    def test_padding_does_not_change_causal_prediction(self):
        t=self.torch;self.model.eval()
        changed=self.ids.clone();changed[0,int(self.lengths[0]):]=9
        with t.no_grad():
            t.testing.assert_close(next_character_logits(self.model,self.ids,self.lengths),
                                   next_character_logits(self.model,changed,self.lengths),rtol=0,atol=0)

    def test_invalid_context_lengths_are_rejected(self):
        for n in (0,7,65):
            with self.assertRaises(ValueError):next_character_logits(self.model,self.ids,self.torch.tensor([n]))


if __name__=="__main__":unittest.main()
