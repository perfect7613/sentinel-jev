import unittest
try:
    import torch
except ImportError:
    torch = None
from steering import activation_hook, validate_alpha

class AlphaTests(unittest.TestCase):
    def test_invalid_strength_rejected(self):
        for value in (-.01, .13, float('nan'), float('inf'), True, '0.08'):
            with self.assertRaises(ValueError): validate_alpha(value)

@unittest.skipIf(torch is None, 'Run modal run steering_checks.py for actual tensor checks')
class HookTests(unittest.TestCase):
    def setUp(self):
        self.layer=torch.nn.Linear(4,4,bias=False)
        with torch.no_grad(): self.layer.weight.copy_(torch.eye(4))
        self.model=torch.nn.Module()
        self.model.layers=torch.nn.ModuleList([self.layer])
        self.x=torch.ones(1,3,4)
        self.vector=torch.tensor([1.,-1.,1.,-1.])
    def test_last_token_only_and_no_input_mutation(self):
        with activation_hook(self.model,self.vector,.08,layer_index=0,layer_config={"decoder_block":"layers.{num}"}) as stats:
            actual=self.layer(self.x)
        self.assertTrue(torch.equal(actual[:,:-1],self.x[:,:-1]))
        self.assertTrue(torch.equal(self.x,torch.ones_like(self.x)))
        self.assertTrue(torch.allclose(actual[:,-1],self.x[:,-1]+.08*self.vector))
        self.assertEqual(stats['hook_calls'],1)
        self.assertEqual(len(self.layer._forward_hooks),0)
    def test_exception_cleans_up_hook(self):
        with self.assertRaises(RuntimeError):
            with activation_hook(self.model,self.vector,.08,layer_index=0,layer_config={"decoder_block":"layers.{num}"}):
                self.layer(self.x)
                raise RuntimeError('generation failed')
        self.assertEqual(len(self.layer._forward_hooks),0)
        self.assertTrue(torch.equal(self.layer(self.x),self.x))
    def test_zero_is_exact_baseline(self):
        with activation_hook(self.model,self.vector,0,layer_index=0,layer_config={"decoder_block":"layers.{num}"}) as stats:
            actual=self.layer(self.x)
        self.assertTrue(torch.equal(actual,self.x))
        self.assertEqual(stats['hook_calls'],0)
