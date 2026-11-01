//! A panel button that runs `cosmic-rice flip`. All the logic lives in the CLI.
use std::path::{Path, PathBuf};
use std::process::Stdio;

use cosmic::app::{Core, Task};
use cosmic::cosmic_theme::ThemeMode;
use cosmic::Element;

const APP_ID: &str = "io.github.atraxsrc.CosmicRiceApplet";

/// The icon for the current state: what the desktop is, or that a flip is running.
fn icon_name(is_dark: bool, busy: bool) -> &'static str {
    match (busy, is_dark) {
        (true, _) => "content-loading-symbolic",
        (false, true) => "weather-clear-night-symbolic",
        (false, false) => "weather-clear-symbolic",
    }
}

/// The installed command if it is in ~/.local/bin, otherwise whatever PATH finds.
/// The panel's PATH often leaves out ~/.local/bin.
fn flip_binary(home: Option<&Path>) -> PathBuf {
    home.map(|h| h.join(".local/bin/cosmic-rice"))
        .filter(|p| p.is_file())
        .unwrap_or_else(|| PathBuf::from("cosmic-rice"))
}

async fn run_flip() -> bool {
    let home = std::env::var_os("HOME").map(PathBuf::from);
    tokio::process::Command::new(flip_binary(home.as_deref()))
        .arg("flip")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .await
        .is_ok_and(|status| status.success())
}

struct Applet {
    core: Core,
    is_dark: bool,
    busy: bool,
}

#[derive(Clone, Debug)]
enum Message {
    Clicked,
    Finished,
}

impl cosmic::Application for Applet {
    type Executor = cosmic::SingleThreadExecutor;
    type Flags = ();
    type Message = Message;
    const APP_ID: &'static str = APP_ID;

    fn core(&self) -> &Core {
        &self.core
    }

    fn core_mut(&mut self) -> &mut Core {
        &mut self.core
    }

    fn init(core: Core, _flags: ()) -> (Self, Task<Message>) {
        let is_dark = core.system_theme_mode().is_dark;
        (Self { core, is_dark, busy: false }, Task::none())
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Clicked if !self.busy => {
                self.busy = true;
                // flip sends its own notification, so the exit code needs no reply here
                return cosmic::task::future(async {
                    run_flip().await;
                    Message::Finished
                });
            }
            Message::Clicked => {}
            Message::Finished => self.busy = false,
        }
        Task::none()
    }

    fn system_theme_mode_update(&mut self, _keys: &[&'static str], new: &ThemeMode) -> Task<Message> {
        self.is_dark = new.is_dark;
        Task::none()
    }

    fn view(&self) -> Element<'_, Message> {
        self.core
            .applet
            .icon_button(icon_name(self.is_dark, self.busy))
            .on_press(Message::Clicked)
            .into()
    }

    fn style(&self) -> Option<cosmic::iced::theme::Style> {
        Some(cosmic::applet::style())
    }
}

fn main() -> cosmic::iced::Result {
    cosmic::applet::run::<Applet>(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn icon_shows_the_mode() {
        assert_eq!(icon_name(true, false), "weather-clear-night-symbolic");
        assert_eq!(icon_name(false, false), "weather-clear-symbolic");
    }

    #[test]
    fn busy_wins_over_the_mode() {
        assert_eq!(icon_name(true, true), "content-loading-symbolic");
        assert_eq!(icon_name(false, true), "content-loading-symbolic");
    }

    #[test]
    fn prefers_the_installed_command() {
        let home = std::env::temp_dir().join(format!("rice-applet-{}", std::process::id()));
        std::fs::create_dir_all(home.join(".local/bin")).unwrap();
        std::fs::write(home.join(".local/bin/cosmic-rice"), "").unwrap();
        assert_eq!(flip_binary(Some(&home)), home.join(".local/bin/cosmic-rice"));
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn falls_back_to_path() {
        assert_eq!(flip_binary(None), PathBuf::from("cosmic-rice"));
        assert_eq!(flip_binary(Some(Path::new("/nonexistent"))), PathBuf::from("cosmic-rice"));
    }
}
