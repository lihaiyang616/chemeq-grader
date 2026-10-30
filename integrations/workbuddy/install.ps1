param(
  [string]$WorkBuddyHome = "",
  [string]$ChemeqExe = "",
  [string[]]$McpArgs = @("mcp"),
  [switch]$DryRun,
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Resolve-WorkBuddyHome {
  param([string]$Explicit)
  if ($Explicit) { return (Resolve-Path $Explicit).Path }
  $candidates = @(
    (Join-Path $env:USERPROFILE ".workbuddy"),
    (Join-Path $env:USERPROFILE ".codebuddy")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
  }
  throw "找不到 WorkBuddy 配置目录（~/.workbuddy 或 ~/.codebuddy）。请用 -WorkBuddyHome 指定。"
}

function Resolve-ChemeqExe {
  param([string]$Explicit)
  if ($Explicit) { return (Resolve-Path $Explicit).Path }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "ChemEq\bin\chemeq.exe"),
    (Join-Path $PSScriptRoot "..\..\chemeq.exe"),
    (Join-Path $PSScriptRoot "..\..\..\chemeq.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
  }
  $command = Get-Command chemeq -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  throw "找不到 chemeq.exe。请用 -ChemeqExe 指向程序路径（发布包解压后的 chemeq.exe）。"
}

$workbuddy = Resolve-WorkBuddyHome -Explicit $WorkBuddyHome
$mcpPath = Join-Path $workbuddy "mcp.json"
$skillDir = Join-Path $workbuddy "skills\chemeq-grade"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

if ($Uninstall) {
  Write-Host "WorkBuddy 配置：$workbuddy"
  if (Test-Path $skillDir) {
    if ($DryRun) { Write-Host "[dry-run] 删除技能目录 $skillDir" }
    else { Remove-Item -Recurse -Force $skillDir; Write-Host "已删除技能目录 $skillDir" }
  }
  if (Test-Path $mcpPath) {
    $backup = "$mcpPath.bak-$stamp"
    if (-not $DryRun) { Copy-Item $mcpPath $backup; Write-Host "已备份 $backup" }
    try {
      $json = Get-Content $mcpPath -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($json.mcpServers -and $json.mcpServers.PSObject.Properties.Name -contains "chemeq") {
        $json.mcpServers.PSObject.Properties.Remove("chemeq")
        if ($DryRun) { Write-Host "[dry-run] 从 mcp.json 移除 chemeq" }
        else {
          $jsonText = $json | ConvertTo-Json -Depth 20
          [System.IO.File]::WriteAllText($mcpPath, $jsonText, $utf8NoBom)
          Write-Host "已从 mcp.json 移除 chemeq（备份：$backup）"
        }
      } else {
        Write-Host "mcp.json 中没有 chemeq 条目"
      }
    } catch {
      throw "mcp.json 不是合法 JSON，未修改：$mcpPath"
    }
  }
  Write-Host "卸载完成。"
  exit 0
}

$exe = Resolve-ChemeqExe -Explicit $ChemeqExe
$binDir = Split-Path $exe -Parent
$skillSource = Join-Path $PSScriptRoot "SKILL.md"
if (-not (Test-Path $skillSource)) {
  throw "找不到 SKILL.md：$skillSource"
}

Write-Host "WorkBuddy 配置：$workbuddy"
Write-Host "ChemEq 程序：  $exe"
if ($DryRun) {
  Write-Host "[dry-run] 复制技能到 $skillDir"
  Write-Host "[dry-run] 在 $mcpPath 中写入 chemeq MCP server"
  exit 0
}

New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
$skillText = Get-Content $skillSource -Raw -Encoding UTF8
$skillText = $skillText.Replace("{{CHEMEQ_EXE}}", $exe)
[System.IO.File]::WriteAllText((Join-Path $skillDir "SKILL.md"), $skillText, $utf8NoBom)
Write-Host "已安装技能：$skillDir"

if (Test-Path $mcpPath) {
  $backup = "$mcpPath.bak-$stamp"
  Copy-Item $mcpPath $backup
  Write-Host "已备份 mcp.json：$backup"
  $json = Get-Content $mcpPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
  $json = [pscustomobject]@{ mcpServers = [pscustomobject]@{} }
}
if (-not $json.mcpServers) {
  $json | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{})
}
$entry = [pscustomobject]@{
  type    = "stdio"
  command = $exe
  args    = @($McpArgs)
}
$json.mcpServers | Add-Member -NotePropertyName chemeq -NotePropertyValue $entry -Force
$jsonText = $json | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($mcpPath, $jsonText, $utf8NoBom)
Write-Host "已写入 MCP 配置：$mcpPath"

Write-Host ""
Write-Host "下一步："
Write-Host "1. 完全退出并重新打开 WorkBuddy。"
Write-Host "2. 在 WorkBuddy 里新建会话，测试：帮我看一下有哪些化学作业（应调用 list_worksheets）。"
Write-Host "3. 启动 ChemEq：双击 启动智批.bat，或运行 `"$exe`" serve --open。"
Write-Host "4. 卸载：.\install.ps1 -Uninstall"
