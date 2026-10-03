"""Representation experiments reuse generation's frozen assembly, not its old prompts."""

PROTOCOL = 'fixed_spec_representation_v1'
REPRESENTATIONS = ('natural', 'checklist', 'structured')
STRATEGIES = ('single_shot', 'iterative_repair', 'independent_sampling')
