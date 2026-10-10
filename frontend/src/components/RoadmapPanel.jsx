function ResourceLinks({ material }) {
  return (
    <div className="resourceLinks">
      {material?.website?.url && (
        <a href={material.website.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${material.website.name}`} title={material.website.name}>
          <svg className="resourceIcon websiteIcon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.4 2.5 3.6 5.5 3.6 9s-1.2 6.5-3.6 9c-2.4-2.5-3.6-5.5-3.6-9S9.6 5.5 12 3Z" /></svg>
          <span>Learn on {material.website.name}</span>
        </a>
      )}
      {material?.youtube?.url && (
        <a href={material.youtube.url} target="_blank" rel="noopener noreferrer" aria-label={`Watch ${material.youtube.title}`} title={material.youtube.title}>
          <svg className="resourceIcon youtubeIcon" viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="4" /><path d="m10 9 5 3-5 3Z" /></svg>
          <span>Watch on YouTube</span>
        </a>
      )}
    </div>
  );
}

export default function RoadmapPanel({ roadmap, progress = '' }) {
  if (!roadmap) {
    return (
      <aside className="roadmapCard empty">
        <div className="emptyIcon">🗺️</div>
        <h2>Your Personalized Learning Path</h2>
        <p>{progress || "Tell me your learning goal in the chat and I'll create your roadmap."}</p>
        {progress && <span className="roadmapLoading" role="status"><i /><i /><i /></span>}
        <div className="hint">Note: “SARP can make mistakes while routing. check Information”</div>
      </aside>
    );
  }

  return (
    <aside className="roadmapCard">
      {progress && <div className="roadmapProgress" role="status">{progress}</div>}
      <div className="roadmapHero">
        <div className="heroIcon">🎯</div>
        <div>
          <p>Goal</p>
          <h2>{roadmap.goal || 'Personalized Learning Goal'}</h2>
          <span>{roadmap.duration || 'Flexible timeline'} · {roadmap.starting_level || 'Level not specified'}</span>
        </div>
      </div>
      <div className="timeline">
        {(roadmap.steps || []).map((step, index) => (
          <div className="timelineItem" key={`${step.title}-${index}`}>
            <div className="stepBadge">{index + 1}</div>
            <div className="stepCard">
              <div className="stepMeta">{step.duration || `Stage ${index + 1}`}</div>
              <h3>{step.title}</h3>
              <p>{step.description}</p>
              <ul>
                {(step.topics || []).map((topic) => <li key={topic}>{topic}</li>)}
              </ul>
              {step.study_material && (
                <div className="studyMaterial">
                  <strong>Study Material</strong>
                  <ResourceLinks material={step.study_material} />
                </div>
              )}
              {(step.topic_materials || []).map((item) => (
                <div className="studyMaterial" key={item.topic}>
                  <strong>{item.topic}</strong>
                  <ResourceLinks material={item.study_material} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      {!!roadmap.projects?.length && (
        <div className="miniSection">
          <h3>Projects</h3>
          {roadmap.projects.map((p) => <p key={p}>✅ {p}</p>)}
        </div>
      )}
      {roadmap.next_action && (
        <div className="nextAction"><strong>Next action:</strong> {roadmap.next_action}</div>
      )}
    </aside>
  );
}
