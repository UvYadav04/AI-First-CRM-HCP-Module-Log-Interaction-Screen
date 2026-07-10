import AIAssistantPanel from "./AIAssistantPanel.jsx";
import InteractionForm from "./InteractionForm.jsx";

export default function LogInteractionScreen() {
  return (
    <div className="split-screen">
      <InteractionForm />
      <AIAssistantPanel />
    </div>
  );
}
