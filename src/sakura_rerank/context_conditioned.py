"""Research-only candidate GRU initialized by bounded left-context state.

Reuse the reference model's modules and parameter names. Only the candidate
encoder's initial hidden state changes; tokenizer, features and scorer stay fixed.
No production protocol, data admission or gate policy is implemented here.
"""


def build_context_conditioned(reference_factory):
    import torch
    from torch import nn

    reference = reference_factory()
    hidden = reference.encoder.hidden_size
    if reference.encoder.num_layers != 1 or reference.encoder.bidirectional:
        raise ValueError("context_conditioning_requires_single_forward_gru")

    class ContextConditionedReranker(nn.Module):
        def __init__(self, embedding, encoder, scorer):
            super().__init__()
            self.embedding = embedding
            self.encoder = encoder
            self.scorer = scorer

        def encode(self, ids, lengths, initial=None):
            output, _ = self.encoder(self.embedding(ids), initial)
            index = torch.clamp(lengths-1, min=0)
            gathered = output.gather(1, index.view(-1, 1, 1).expand(-1, 1, hidden)).squeeze(1)
            return gathered*(lengths > 0).to(gathered.dtype).unsqueeze(1)

        def forward(self, context_ids, context_lengths, reading_ids, reading_lengths,
                    candidate_ids, candidate_lengths, features, candidate_mask):
            batch, count, width = candidate_ids.shape
            context = self.encode(context_ids, context_lengths)
            reading = self.encode(reading_ids, reading_lengths)
            initial = context.unsqueeze(1).expand(-1, count, -1).reshape(1, batch*count, hidden).contiguous()
            candidates = self.encode(candidate_ids.reshape(batch*count, width),
                                     candidate_lengths.reshape(batch*count), initial).reshape(batch, count, hidden)
            joined = torch.cat((context.unsqueeze(1).expand(-1, count, -1),
                                reading.unsqueeze(1).expand(-1, count, -1), candidates, features), dim=2)
            scores = features[:, :, 0]*2.0+self.scorer(joined).squeeze(2)
            return scores.masked_fill(~candidate_mask, -10000.0)

    return ContextConditionedReranker(reference.embedding, reference.encoder, reference.scorer)
