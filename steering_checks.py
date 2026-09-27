"""Run the real PyTorch hook unit tests in the deployed model's CPU image."""
from pathlib import Path
import modal
if modal.is_local():
    from modal_model import image
else:
    image = modal.Image.debian_slim()
app=modal.App('sentinel-steering-checks')
image=image.add_local_file(Path(__file__).parent/'tests/test_steering.py','/root/test_steering.py')
@app.function(image=image,timeout=120)
def check():
    import unittest
    suite=unittest.defaultTestLoader.discover('/root',pattern='test_steering.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped: raise RuntimeError('Hook verification incomplete')
    return {'tests':result.testsRun,'passed':True}
@app.local_entrypoint()
def main(): print(check.remote())
