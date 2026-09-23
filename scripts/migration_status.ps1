param([string]$DatabaseUrl = $env:DATABASE_URL)
if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) { throw "Set DATABASE_URL before checking migration status." }
$env:DATABASE_URL = $DatabaseUrl
Push-Location (Join-Path $PSScriptRoot "..\apps\api")
try { python -m alembic current } finally { Pop-Location }
