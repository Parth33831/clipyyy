Option Explicit

Dim fso, shell, scriptDir, launcher, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(scriptDir, "Start-Clipyyy.bat")
shell.CurrentDirectory = scriptDir

If Not fso.FileExists(launcher) Then
  WScript.Quit 1
End If

command = "cmd.exe /d /c " & Chr(34) & Chr(34) & launcher & Chr(34) & Chr(34)
shell.Run command, 0, False
