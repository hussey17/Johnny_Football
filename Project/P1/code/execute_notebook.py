"""Execute the P1 notebook using exactly the Python interpreter running this file."""
from pathlib import Path
import json,sys,tempfile,os
for name in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:
    os.environ[name]='1'
import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager
root=Path(__file__).resolve().parents[1]
path=root/'notebooks/nonvoters_selection_2016_2024.ipynb'
nb=nbformat.read(path,as_version=4)
with tempfile.TemporaryDirectory(prefix='p1-kernels-') as tmp:
    spec=Path(tmp)/'python3';spec.mkdir()
    (spec/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],
       'display_name':'Python 3 (P1)','language':'python'}))
    km=KernelManager(kernel_name='python3',kernel_spec_manager=KernelSpecManager(kernel_dirs=[tmp]))
    def on_cell_complete(cell,cell_index,**kwargs):
        print(f'Cell {cell_index+1}/{len(nb.cells)} completed',flush=True)
        nbformat.write(nb,path)
    client=NotebookClient(nb,km=km,timeout=1800,resources={'metadata':{'path':str(root)}},on_cell_executed=on_cell_complete)
    try:
        client.execute()
    finally:
        nbformat.write(nb,path)
errors=[(i,o) for i,c in enumerate(nb.cells) if c.cell_type=='code' for o in c.outputs if o.output_type=='error']
assert not errors, errors
nbformat.validate(nb)
print('Executed and validated:',path)
