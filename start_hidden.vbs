' Silent launcher for qiandao web console (port 5050).
' Delegates all detection/startup logic to run_web.bat (idempotent: reuses a
' healthy listener, starts only when port 5050 is free). Never opens a browser.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run "cmd /c """ & projectDir & "\run_web.bat""", 0, False
