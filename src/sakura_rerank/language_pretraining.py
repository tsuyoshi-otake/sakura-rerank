"""A training-only tied character head; production ranker structure is unchanged."""


def encoder_parameters(model):
    for name,parameter in model.named_parameters():
        parameter.requires_grad_(name.startswith(("embedding.","encoder.")))
    return [p for p in model.parameters() if p.requires_grad]


def next_character_logits(model,context_ids,lengths):
    import torch
    if context_ids.ndim!=2 or context_ids.shape[1]!=64 or lengths.shape!=(len(context_ids),):
        raise ValueError("language_input_shape")
    if torch.any(lengths<8) or torch.any(lengths>64):raise ValueError("language_context_bounds")
    state=model.encode(context_ids,lengths)
    logits=torch.nn.functional.linear(state,model.embedding.weight)
    # Padding is not a character target. Clone keeps the tied parameter intact.
    logits=logits.clone();logits[:,0]=-10_000.0
    return logits
