# Dafny CodeGen Pipeline 环境激活脚本
Write-Host "☀️ 激活 CodeGen Pipeline 环境..."

# 激活 Python 虚拟环境
& "$PSScriptRoot\env\Scripts\Activate.ps1"

# 添加 Dafny 到 PATH
$env:Path += ";D:\tools\dafny\dafny"

# 提示
Write-Host "✅ 环境就绪"
Write-Host "  Python: $(python --version)"
Write-Host "  Dafny:  $(dafny --version 2>$null)"
Write-Host ""
Write-Host "项目目录: $PSScriptRoot\project"
