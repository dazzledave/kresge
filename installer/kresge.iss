; ---------------------------------------------------------------------------
; Inno Setup script for Kresge.
;
; Packages the PyInstaller one-folder build (dist\Kresge\) into a Windows
; installer: dist\KresgeSetup-<version>.exe
;
; Normally run via build.bat, which passes the version from
; kresge\__init__.py as /DAppVersion=x.y.z.
; ---------------------------------------------------------------------------

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Kresge"
#define AppExe "Kresge.exe"

[Setup]
; AppId identifies the app for upgrades/uninstall — never change it.
AppId={{1DDD421E-5E05-41B9-A04A-ED84E1446B20}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=dazzledave
AppPublisherURL=https://github.com/dazzledave/kresge
AppSupportURL=https://github.com/dazzledave/kresge/issues
AppUpdatesURL=https://github.com/dazzledave/kresge/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile=..\kresge\ui\assets\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\dist
OutputBaseFilename=KresgeSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running Kresge (it lives in the tray) before upgrading files.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Clear the previous build's bundled files so upgrades don't leave stale DLLs.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Kresge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
; The "(Administrator)" shortcut gets its run-as-admin bit set in [Code] below.
Name: "{group}\{#AppName} (Administrator)"; Filename: "{app}\{#AppExe}"; Comment: "Run elevated for per-device hotspot usage and blocking"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "KillKresge"

[Code]
// Set the "Run as administrator" bit on a .lnk file (byte 0x15, flag 0x20).
procedure SetRunAsAdmin(const LnkPath: String);
var
  Stream: TFileStream;
  Buffer: AnsiString;
begin
  if not FileExists(LnkPath) then
    Exit;
  Stream := TFileStream.Create(LnkPath, fmOpenReadWrite);
  try
    Stream.Seek($15, soFromBeginning);
    SetLength(Buffer, 1);
    Stream.ReadBuffer(Buffer, 1);
    Buffer[1] := Chr(Ord(Buffer[1]) or $20);
    Stream.Seek($15, soFromBeginning);
    Stream.WriteBuffer(Buffer, 1);
  finally
    Stream.Free;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SetRunAsAdmin(ExpandConstant('{group}\{#AppName} (Administrator).lnk'));
end;
