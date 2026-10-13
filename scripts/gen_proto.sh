#!/bin/bash
# 重新生成 protobuf 与 FlatBuffers 的 Python 代码
#
# 前置：
#   - pip install grpcio-tools flatbuffers
#   - flatc 可执行文件（https://github.com/google/flatbuffers/releases 下载 Mac.flatc.binary.zip）
#
# 用法：scripts/gen_proto.sh [flatc路径]

set -e

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

FLATC="${1:-flatc}"
GRPC_PORT_DEFAULT=7859

echo "==> 生成 protobuf (imageService.proto)"
mkdir -p src/grpc_gen
./venv/bin/python -m grpc_tools.protoc \
    -I proto \
    --python_out=src/grpc_gen \
    --grpc_python_out=src/grpc_gen \
    --pyi_out=src/grpc_gen \
    proto/imageService.proto

# 生成代码用的是扁平导入（import imageService_pb2），在包内会失败，统一改成相对导入
./venv/bin/python - <<'PYEOF'
import re, pathlib
d = pathlib.Path('src/grpc_gen')
fixed = 0
for f in d.glob('*_grpc.py'):
    src = f.read_text(encoding='utf-8')
    new = re.sub(r'^import imageService_pb2 as', 'from . import imageService_pb2 as', src, flags=re.M)
    if new != src:
        f.write_text(new, encoding='utf-8')
        fixed += 1
print(f'    修复 {fixed} 个文件的导入')
PYEOF

echo "==> 生成 FlatBuffers (config.fbs)"
mkdir -p src/fb_gen
"$FLATC" --python --gen-object-api -o src/fb_gen proto/config.fbs

# 同样存在扁平导入问题，且函数内部还有延迟导入
./venv/bin/python - <<'PYEOF'
import re, pathlib
names = ['GenerationConfiguration','LoRA','Control','SamplerType','SeedMode',
         'LoRAMode','ControlMode','ControlInputType','CompressionMethod','ColorCalibration']
alt = '|'.join(names)
d = pathlib.Path('src/fb_gen')
fixed = 0
for f in d.glob('*.py'):
    if f.name == '__init__.py':
        continue
    src = f.read_text(encoding='utf-8')
    # 模块级与函数内的延迟导入都要改
    new = re.sub(rf'^(\s+)import ({alt})$', rf'\1from . import \2', src, flags=re.M)
    new = re.sub(rf'^(\s+)from ({alt}) import ', r'\1from .\2 import ', new, flags=re.M)
    if new != src:
        f.write_text(new, encoding='utf-8')
        fixed += 1
print(f'    修复 {fixed} 个文件的导入')
PYEOF

echo "==> 验证"
./venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from src.grpc_gen import imageService_pb2, imageService_pb2_grpc
from src.fb_gen.GenerationConfiguration import GenerationConfiguration, GenerationConfigurationT
from src import dt_config, dt_tensor, grpc_client, backend
print('    全部模块导入成功')
"

echo "==> 完成"