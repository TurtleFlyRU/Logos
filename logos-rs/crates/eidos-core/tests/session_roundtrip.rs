use eidos_core::resolve_paths;
use eidos_core::session::{read_latest, touch_session, write_latest};

#[test]
fn session_latest_roundtrip() {
    let paths = match resolve_paths() {
        Ok(p) => p,
        Err(_) => return,
    };
    let sid = "00000000-0000-4000-8000-000000000001";
    touch_session(&paths, sid).expect("touch");
    write_latest(&paths, sid).expect("latest");
    assert_eq!(read_latest(&paths).as_deref(), Some(sid));
}
