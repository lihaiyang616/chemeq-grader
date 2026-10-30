param(
  [string]$WorkBuddyHome = ""
)

$installer = Join-Path $PSScriptRoot "install.ps1"
if (-not (Test-Path $installer)) { throw "找不到 install.ps1" }
if ($WorkBuddyHome) {
  & $installer -Uninstall -WorkBuddyHome $WorkBuddyHome
} else {
  & $installer -Uninstall
}
