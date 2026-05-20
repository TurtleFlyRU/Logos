// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

/// WebKitGTK на Linux/WSL часто требует явный IM-модуль до инициализации GTK.
fn init_linux_input_method() {
    #[cfg(target_os = "linux")]
    {
        if std::env::var("GTK_IM_MODULE").is_err() {
            // IBUS чаще всего уже есть в WSLg/Ubuntu; fcitx — запасной вариант (см. README).
            std::env::set_var("GTK_IM_MODULE", "ibus");
        }
        if std::env::var("XMODIFIERS").is_err() {
            let module = std::env::var("GTK_IM_MODULE").unwrap_or_else(|_| "ibus".into());
            std::env::set_var("XMODIFIERS", format!("@im={module}"));
        }
        if std::env::var("LANG").is_err() {
            std::env::set_var("LANG", "ru_RU.UTF-8");
        }
    }
}

fn main() {
    init_linux_input_method();
    eidos_desktop_lib::run()
}
