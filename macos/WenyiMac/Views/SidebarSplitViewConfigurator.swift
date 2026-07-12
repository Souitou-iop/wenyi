import AppKit
import SwiftUI

enum SidebarWidthPolicy {
    static let minimum: CGFloat = 180
    static let ideal: CGFloat = 230
    static let maximum: CGFloat = 280
    static let autosaveName = "WenyiSidebarSplitView"

    @MainActor
    static func configure(_ item: NSSplitViewItem, in splitView: NSSplitView) {
        item.minimumThickness = minimum
        item.maximumThickness = maximum
        item.canCollapse = true
        splitView.autosaveName = autosaveName
    }
}

struct SidebarSplitViewConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        ProbeView()
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        (nsView as? ProbeView)?.scheduleConfiguration()
    }
}

private final class ProbeView: NSView {
    private weak var configuredItem: NSSplitViewItem?

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        scheduleConfiguration()
    }

    override func viewDidMoveToSuperview() {
        super.viewDidMoveToSuperview()
        scheduleConfiguration()
    }

    func scheduleConfiguration() {
        DispatchQueue.main.async { [weak self] in
            self?.configureSplitView()
        }
    }

    private func configureSplitView() {
        guard let rootController = window?.contentViewController,
              let splitController = findSplitController(in: rootController),
              let sidebarItem = splitController.splitViewItems.first(where: {
                  isDescendant(of: $0.viewController.view)
              })
        else { return }

        SidebarWidthPolicy.configure(sidebarItem, in: splitController.splitView)
        configuredItem = sidebarItem
    }

    private func findSplitController(in controller: NSViewController) -> NSSplitViewController? {
        if let splitController = controller as? NSSplitViewController,
           splitController.splitViewItems.contains(where: {
               isDescendant(of: $0.viewController.view)
           }) {
            return splitController
        }
        for child in controller.children {
            if let found = findSplitController(in: child) {
                return found
            }
        }
        return nil
    }
}
