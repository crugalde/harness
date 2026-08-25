<#
.SYNOPSIS
    Opera n8n en el VPS desde Windows, sin abrir nunca una shell de Linux.

.DESCRIPTION
    Cada acción envuelve los comandos que corren en el VPS y los ejecuta por SSH desde
    PowerShell. Los valores por defecto ya apuntan a este proyecto, así que en el caso
    normal basta con la acción.

    Requisitos: OpenSSH (ssh/scp) y tar — ambos vienen con Windows 10/11 — y Python 3
    para los pasos que corren en tu máquina.

.EXAMPLE
    .\n8n.ps1 check                      # verifica herramientas y conexión al VPS
    .\n8n.ps1 sync                       # copia el proyecto al VPS
    .\n8n.ps1 preflight                  # diagnóstico previo, guarda la salida
    .\n8n.ps1 deploy -Email tu@correo.cl # levanta el stack
    .\n8n.ps1 export                     # exporta los workflows desde n8n Cloud
    .\n8n.ps1 upload                     # sube los JSON exportados al VPS
    .\n8n.ps1 import                     # remapea credenciales e importa
    .\n8n.ps1 status                     # estado de los contenedores
    .\n8n.ps1 logs -Servicio caddy       # logs (n8n por defecto)
    .\n8n.ps1 backup                     # respaldo manual
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('check', 'sync', 'preflight', 'deploy', 'export', 'upload', 'import',
                 'status', 'logs', 'backup', 'harness')]
    [string]$Accion = 'check',

    [string]$VpsHost   = 'root@srv1314177',
    [string]$Dominio   = 'n8n.neuromuscular.cloud',
    [string]$CloudUrl  = 'https://cristianub.app.n8n.cloud',
    [string]$Email     = '',
    [string]$RemoteDir = '/opt/n8n',
    [string]$ExportDir = "$HOME\n8n_export",
    [string]$Servicio  = 'n8n'
)

$ErrorActionPreference = 'Stop'

# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

$ProyectoDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$RepoDir     = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path

function Write-Paso  { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Aviso { param([string]$m) Write-Host "    $m" -ForegroundColor Yellow }

function Assert-Herramienta {
    param([string]$Nombre, [string]$Ayuda)
    if (-not (Get-Command $Nombre -ErrorAction SilentlyContinue)) {
        throw "Falta '$Nombre'. $Ayuda"
    }
}

function Get-Python {
    foreach ($cmd in @('python', 'python3')) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { return $cmd }
    }
    if (Get-Command 'py' -ErrorAction SilentlyContinue) { return 'py' }
    throw "No encontré Python. Instálalo con:  winget install Python.Python.3.12"
}

function Invoke-Vps {
    <# Corre un comando en el VPS por SSH y falla fuerte si el remoto falla. #>
    param([Parameter(Mandatory)][string]$Comando, [switch]$PermitirFallo)
    & ssh $VpsHost $Comando
    if ($LASTEXITCODE -ne 0 -and -not $PermitirFallo) {
        throw "El comando remoto falló (código $LASTEXITCODE): $Comando"
    }
}

function Send-Directorio {
    <# Empaqueta un directorio local y lo descomprime en el VPS.

       Usa tar en vez de 'scp -r origen\*' a propósito: PowerShell no expande comodines
       para comandos nativos, así que ese patrón copia mal o no copia nada. Además el
       tar respeta lo que ya existe en el destino (.env, backups/) porque solo sobrescribe
       los archivos del paquete. #>
    param([Parameter(Mandatory)][string]$Origen, [Parameter(Mandatory)][string]$Destino)

    if (-not (Test-Path $Origen)) { throw "No existe el directorio local: $Origen" }
    $tmp = Join-Path $env:TEMP ("n8n_" + [System.Guid]::NewGuid().ToString('N') + ".tgz")
    try {
        & tar -czf $tmp -C $Origen .
        if ($LASTEXITCODE -ne 0) { throw "tar falló empaquetando $Origen" }

        & scp $tmp "${VpsHost}:/tmp/n8n_upload.tgz"
        if ($LASTEXITCODE -ne 0) { throw "scp falló subiendo el paquete al VPS" }

        Invoke-Vps "mkdir -p '$Destino' && tar -xzf /tmp/n8n_upload.tgz -C '$Destino' && rm -f /tmp/n8n_upload.tgz"
    }
    finally {
        if (Test-Path $tmp) { Remove-Item $tmp -Force }
    }
}

# --------------------------------------------------------------------------- #
# Acciones
# --------------------------------------------------------------------------- #

function Accion-Check {
    Write-Paso "Herramientas locales"
    Assert-Herramienta 'ssh'  "Actívalo en Configuración → Aplicaciones → Características opcionales → Cliente OpenSSH."
    Assert-Herramienta 'scp'  "Viene con el Cliente OpenSSH de Windows."
    Assert-Herramienta 'tar'  "Viene con Windows 10 (1803+) y Windows 11."
    Write-Ok "ssh, scp y tar disponibles"
    $py = Get-Python
    Write-Ok "Python: $py"

    Write-Paso "Conexión al VPS ($VpsHost)"
    & ssh -o BatchMode=yes -o ConnectTimeout=10 $VpsHost 'echo conectado'
    if ($LASTEXITCODE -ne 0) {
        Write-Aviso "No se pudo conectar sin contraseña. Si usas clave con passphrase o contraseña,"
        Write-Aviso "conéctate una vez a mano:  ssh $VpsHost"
    } else {
        Write-Ok "SSH sin contraseña funcionando"
    }

    Write-Paso "DNS de $Dominio"
    $res = $null
    if (Get-Command Resolve-DnsName -ErrorAction SilentlyContinue) {
        $res = Resolve-DnsName -Name $Dominio -Type A -ErrorAction SilentlyContinue
    }
    if ($res) {
        Write-Ok ("$Dominio -> " + ($res | Where-Object { $_.IPAddress } | Select-Object -First 1).IPAddress)
    } else {
        Write-Aviso "$Dominio todavía no resuelve: crea el registro A antes de 'deploy'."
    }
}

function Accion-Sync {
    Write-Paso "Copiando el proyecto a ${VpsHost}:$RemoteDir"
    Send-Directorio -Origen $ProyectoDir -Destino $RemoteDir
    Write-Ok "Proyecto sincronizado (tu .env y tus backups en el VPS quedan intactos)"
}

function Accion-Preflight {
    $salida = Join-Path $HOME 'preflight.txt'
    Write-Paso "Preflight contra $Dominio"
    & ssh $VpsHost "bash $RemoteDir/scripts/preflight.sh $Dominio" | Tee-Object -FilePath $salida
    $codigo = $LASTEXITCODE
    Write-Host ""
    Write-Ok "Salida guardada en $salida"
    if ($codigo -ne 0) {
        Write-Aviso "Hay puntos marcados con X. Arréglalos antes de 'deploy'."
    }
}

function Accion-Deploy {
    if (-not $Email) { throw "Falta -Email (lo usa Let's Encrypt para avisos de certificado)." }
    Write-Paso "Levantando el stack en $Dominio"
    Invoke-Vps "bash $RemoteDir/scripts/bootstrap_vps.sh --domain $Dominio --email $Email"
    Write-Ok "Abre https://$Dominio y crea la cuenta de owner"
    Write-Aviso "Guarda la N8N_ENCRYPTION_KEY que imprimió: sin ella las credenciales son irrecuperables."
}

function Accion-Export {
    if (-not $env:N8N_API_KEY) {
        throw "Falta la API key. Créala en Settings -> n8n API y expórtala:`n" +
              "  `$env:N8N_API_KEY = 'n8n_api_...'"
    }
    $py     = Get-Python
    $exportScript = Join-Path $ProyectoDir 'scripts\export_cloud.py'
    Write-Paso "Exportando workflows desde $CloudUrl"
    & $py $exportScript --base-url $CloudUrl --out $ExportDir --new-domain $Dominio
    if ($LASTEXITCODE -ne 0) { throw "El export falló (ver el mensaje de arriba)." }
    Write-Ok "Revisa $ExportDir\inventario_credenciales.md y $ExportDir\resumen.md"
}

function Accion-Upload {
    $wf = Join-Path $ExportDir 'workflows'
    if (-not (Test-Path $wf)) { throw "No existe $wf. Corre primero:  .\n8n.ps1 export" }
    $n = (Get-ChildItem $wf -Filter *.json).Count
    Write-Paso "Subiendo $n workflows a ${VpsHost}:$RemoteDir/export_workflows"
    Send-Directorio -Origen $wf -Destino "$RemoteDir/export_workflows"
    Write-Ok "Listo. Siguiente:  .\n8n.ps1 import"
}

function Accion-Import {
    Write-Paso "Mapa de credenciales del VPS"
    Invoke-Vps "cd $RemoteDir && bash scripts/credenciales_map.sh > map.json && wc -c map.json"
    Write-Paso "Reapuntando IDs de credencial"
    # remap sale 1 cuando alguna credencial no tiene equivalente: es informativo, no un fallo.
    Invoke-Vps "cd $RemoteDir && python3 scripts/remap_credentials.py --dir export_workflows --map map.json" -PermitirFallo
    Write-Paso "Importando"
    Invoke-Vps "cd $RemoteDir && bash scripts/import_vps.sh export_workflows_remap"
    Write-Ok "Los workflows quedan INACTIVOS: actívalos uno a uno en https://$Dominio"
}

function Accion-Status {
    Write-Paso "Contenedores"
    Invoke-Vps "cd $RemoteDir/deploy && docker compose ps"
    Write-Paso "Salud de n8n"
    Invoke-Vps "curl -sS -o /dev/null -w 'HTTP %{http_code}\n' https://$Dominio/healthz" -PermitirFallo
}

function Accion-Logs {
    Write-Paso "Últimas 60 líneas de $Servicio"
    Invoke-Vps "cd $RemoteDir/deploy && docker compose logs --tail 60 $Servicio"
}

function Accion-Backup {
    Write-Paso "Respaldo manual"
    Invoke-Vps "bash $RemoteDir/scripts/backup.sh"
}

function Accion-Harness {
    $py = Get-Python
    Write-Paso "Estado del harness contra n8n"
    & $py (Join-Path $RepoDir 'tools\n8n_setup.py') status
}

# --------------------------------------------------------------------------- #

try {
    switch ($Accion) {
        'check'     { Accion-Check }
        'sync'      { Accion-Sync }
        'preflight' { Accion-Preflight }
        'deploy'    { Accion-Deploy }
        'export'    { Accion-Export }
        'upload'    { Accion-Upload }
        'import'    { Accion-Import }
        'status'    { Accion-Status }
        'logs'      { Accion-Logs }
        'backup'    { Accion-Backup }
        'harness'   { Accion-Harness }
    }
}
catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
