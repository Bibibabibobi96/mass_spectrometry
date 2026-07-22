# SIMION公共序列化层

本目录只保存不含器件几何、坐标系或运行模式假设的SIMION文本序列化。`particle_source.py`接收已经由
上游适配器转换到工作台语义的beam或逐粒子状态并生成FLY2/Lua文本；多极杆的ION11和canonical字段映射
仍由`common/multipole/simion_particle_source.py`负责。

本层不启动SIMION、不选择PA/IOB、不解释电极编号，也不维护物理参数。统一求解器命令包装器仍属于
Roadmap中的未来平台任务。
