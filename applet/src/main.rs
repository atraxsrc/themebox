//! A panel button that runs `themebox flip`. All the logic lives in the CLI.
use std::path::{Path, PathBuf};
use std::process::Stdio;

use cosmic::app::{Core, Task};
use cosmic::cosmic_theme::ThemeMode;
use cosmic::widget::icon;
use cosmic::Element;

const APP_ID: &str = "io.github.atraxsrc.ThemeboxApplet";

// The two halves of assets/logo.svg. Built in, because the prebuilt applet installs as a lone binary.
const MOON: &[u8] = include_bytes!("../data/icons/moon-symbolic.svg");
const SUN: &[u8] = include_bytes!("../data/icons/sun-symbolic.svg");

#[derive(Debug, PartialEq)]
enum PanelIcon {
    Moon,
    Sun,
    Busy,
}

/// The icon for the current state: what the desktop is, or that a flip is running.
fn panel_icon(is_dark: bool, busy: bool) -> PanelIcon {
    match (busy, is_dark) {
        (true, _) => PanelIcon::Busy,
        (false, true) => PanelIcon::Moon,
        (false, false) => PanelIcon::Sun,
    }
}

/// Symbolic, so the panel tints it with its own text colour on every rice.
fn logo_half(svg: &'static [u8]) -> icon::Handle {
    icon::from_svg_bytes(svg).symbolic(true)
}

/// The installed command if it is in ~/.local/bin, otherwise whatever PATH finds.
/// The panel's PATH often leaves out ~/.local/bin.
fn flip_binary(home: Option<&Path>) -> PathBuf {
    home.map(|h| h.join(".local/bin/themebox"))
        .filter(|p| p.is_file())
        .unwrap_or_else(|| PathBuf::from("themebox"))
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
        let applet = &self.core.applet;
        let button = match panel_icon(self.is_dark, self.busy) {
            PanelIcon::Moon => applet.icon_button_from_handle(logo_half(MOON)),
            PanelIcon::Sun => applet.icon_button_from_handle(logo_half(SUN)),
            PanelIcon::Busy => applet.icon_button("content-loading-symbolic"),
        };
        button.on_press(Message::Clicked).into()
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
        assert_eq!(panel_icon(true, false), PanelIcon::Moon);
        assert_eq!(panel_icon(false, false), PanelIcon::Sun);
    }

    #[test]
    fn busy_wins_over_the_mode() {
        assert_eq!(panel_icon(true, true), PanelIcon::Busy);
        assert_eq!(panel_icon(false, true), PanelIcon::Busy);
    }

    #[test]
    fn logo_halves_take_the_panel_colour() {
        assert!(logo_half(MOON).symbolic);
        assert!(logo_half(SUN).symbolic);
    }

    #[test]
    fn prefers_the_installed_command() {
        let home = std::env::temp_dir().join(format!("rice-applet-{}", std::process::id()));
        std::fs::create_dir_all(home.join(".local/bin")).unwrap();
        std::fs::write(home.join(".local/bin/themebox"), "").unwrap();
        assert_eq!(flip_binary(Some(&home)), home.join(".local/bin/themebox"));
        std::fs::remove_dir_all(&home).unwrap();
    }

    #[test]
    fn falls_back_to_path() {
        assert_eq!(flip_binary(None), PathBuf::from("themebox"));
        assert_eq!(flip_binary(Some(Path::new("/nonexistent"))), PathBuf::from("themebox"));
    }
}
