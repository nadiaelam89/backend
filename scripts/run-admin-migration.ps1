# Run admin dashboard SQL migration on PostgreSQL
# Usage (EasyPanel terminal or machine with DB access):
#   $env:DATABASE_URL="postgresql://user:pass@host:5432/dbname"
#   .\scripts\run-admin-migration.ps1

param(
    [string]$DatabaseUrl = $env:DATABASE_URL
)

if (-not $DatabaseUrl) {
    Write-Error "Set DATABASE_URL first. Example: postgresql://sukoonhealth:PASSWORD@host:5432/sukoonhealth"
    exit 1
}

# psql expects postgresql:// not postgresql+asyncpg://
$PsqlUrl = $DatabaseUrl -replace '^postgresql\+asyncpg', 'postgresql'

$sqlFile = Join-Path $PSScriptRoot "..\app\db\migrations\sql\0002_admin_dashboard.sql"
if (-not (Test-Path $sqlFile)) {
    Write-Error "SQL file not found: $sqlFile"
    exit 1
}

Write-Host "Running migration from $sqlFile"
psql $PsqlUrl -f $sqlFile
if ($LASTEXITCODE -eq 0) {
    Write-Host "Migration completed successfully."
} else {
    Write-Error "Migration failed (exit $LASTEXITCODE)."
    exit $LASTEXITCODE
}
